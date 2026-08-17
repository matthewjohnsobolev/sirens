/**
 * Serves the built Evidence dashboard out of an R2 bucket.
 *
 * R2 has no notion of an index document and serves objects by exact key, so
 * mapping request paths to keys is the whole job of this Worker. Why R2 rather
 * than Pages, and how it is deployed: see wrangler.toml and README.md.
 */

const INDEX = 'index.html';

// Evidence content-hashes everything under this prefix, so those URLs can never
// point at different bytes. Anything else is rebuilt daily under the same name.
const IMMUTABLE_PREFIX = '_app/immutable/';
const IMMUTABLE_CACHE = 'public, max-age=31536000, immutable';
const MUTABLE_CACHE = 'public, max-age=300, must-revalidate';

// The uploader's guesses are not trustworthy for these (the aws CLI has no
// entry for .wasm or .parquet), and duckdb-wasm refuses to instantiate a
// module that did not arrive as application/wasm.
const CONTENT_TYPES = {
    css: 'text/css; charset=utf-8',
    csv: 'text/csv; charset=utf-8',
    html: 'text/html; charset=utf-8',
    ico: 'image/x-icon',
    js: 'text/javascript; charset=utf-8',
    json: 'application/json; charset=utf-8',
    map: 'application/json; charset=utf-8',
    parquet: 'application/vnd.apache.parquet',
    png: 'image/png',
    svg: 'image/svg+xml',
    txt: 'text/plain; charset=utf-8',
    wasm: 'application/wasm',
    woff: 'font/woff',
    woff2: 'font/woff2',
};

function candidateKeys(pathname) {
    let key;
    try {
        key = decodeURIComponent(pathname);
    } catch {
        key = pathname; // malformed percent-encoding: try it literally
    }
    key = key.replace(/^\/+/, '');

    if (key === '' || key.endsWith('/')) {
        return [key + INDEX];
    }
    if (key.includes('.')) {
        return [key];
    }
    // Evidence emits pretty URLs as directories: /channels -> channels/index.html
    return [key, `${key}/${INDEX}`, `${key}.html`];
}

function contentTypeFor(key) {
    const extension = key.split('.').pop().toLowerCase();
    return CONTENT_TYPES[extension];
}

function contentRange(range, size) {
    const start = range.offset ?? size - range.suffix;
    const end = range.length === undefined ? size - 1 : start + range.length - 1;
    return `bytes ${start}-${end}/${size}`;
}

function buildHeaders(object, key) {
    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set('etag', object.httpEtag);
    headers.set('cache-control', key.startsWith(IMMUTABLE_PREFIX) ? IMMUTABLE_CACHE : MUTABLE_CACHE);
    headers.set('accept-ranges', 'bytes');
    headers.set('x-content-type-options', 'nosniff');

    const contentType = contentTypeFor(key);
    if (contentType) {
        headers.set('content-type', contentType);
    }

    return headers;
}

async function serve(bucket, key, request) {
    const object = await bucket.get(key, {
        // Range so duckdb-wasm can read parquet in pieces instead of pulling
        // whole files; onlyIf so a repeat visitor gets a 304 rather than 40 MB.
        range: request.headers,
        onlyIf: request.headers,
    });

    if (object === null) {
        return null;
    }

    const headers = buildHeaders(object, key);

    // A failed precondition comes back as a plain R2Object: the docs say `body`
    // is undefined, the canonical example tests `"body" in object`. Cover both,
    // or an unlucky shape slips through and we answer 200 with an empty body.
    if (!('body' in object) || object.body == null) {
        // R2 reports every failed precondition identically, so only the request
        // says which answer is right: a browser revalidating with If-None-Match
        // wants 304, while a failed If-Match is 412.
        const revalidating =
            request.headers.has('if-none-match') || request.headers.has('if-modified-since');
        return new Response(null, { status: revalidating ? 304 : 412, headers });
    }

    let status = 200;
    if (object.range && request.headers.has('range')) {
        headers.set('content-range', contentRange(object.range, object.size));
        status = 206;
    }

    return new Response(request.method === 'HEAD' ? null : object.body, { status, headers });
}

export default {
    async fetch(request, env) {
        if (request.method !== 'GET' && request.method !== 'HEAD') {
            return new Response('method not allowed\n', {
                status: 405,
                headers: { allow: 'GET, HEAD', 'content-type': 'text/plain; charset=utf-8' },
            });
        }

        const { pathname } = new URL(request.url);

        for (const key of candidateKeys(pathname)) {
            const response = await serve(env.STATIC, key, request);
            if (response !== null) {
                return response;
            }
        }

        const notFound = await env.STATIC.get('404.html');
        if (notFound !== null) {
            return new Response(notFound.body, {
                status: 404,
                headers: { 'content-type': CONTENT_TYPES.html, 'cache-control': MUTABLE_CACHE },
            });
        }

        return new Response('not found\n', {
            status: 404,
            headers: { 'content-type': 'text/plain; charset=utf-8' },
        });
    },
};

