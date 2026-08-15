/**
 * Serves the built Evidence dashboard out of an R2 bucket.
 *
 * Why this exists: Cloudflare Pages rejects any file over 25 MiB, and Evidence
 * ships a 32.7 MiB duckdb-eh.wasm, so the site cannot live there. R2 has no
 * such limit - but it also has no notion of an index document, and no way to
 * put Access in front of a raw bucket. Mapping request paths to object keys is
 * the whole job of this Worker.
 *
 * CI only syncs files into the bucket. This Worker is infrastructure: deploy it
 * by hand from dashboard/worker with `npx wrangler deploy`, which is needed
 * roughly never.
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

    if (!('body' in object) || object.body === null) {
        return new Response(null, { status: 304, headers });
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
            const response = await serve(env.SITE, key, request);
            if (response !== null) {
                return response;
            }
        }

        const notFound = await env.SITE.get('404.html');
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
