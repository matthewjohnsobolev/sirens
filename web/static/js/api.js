const API_URL = '/api';
const API_TIMEOUT = 8000;

// A map that gave up on its first failed request would keep showing the
// country as it stood before anything happened, and say nothing about it.
const API_RETRY_DELAYS = [400, 1200, 3000];

function fetchWithTimeout(url, timeout) {
    if (typeof AbortController === 'undefined') return fetch(url);

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const done = () => clearTimeout(timer);

    return fetch(url, { signal: controller.signal }).then(
        response => { done(); return response; },
        error => { done(); throw error; }
    );
}

function fetchJson(url, attempt = 0) {
    return fetchWithTimeout(url, API_TIMEOUT)
        .then(response => {
            if (!response.ok) throw new Error(`${url} responded ${response.status}`);
            return response.json();
        })
        .catch(error => {
            if (attempt >= API_RETRY_DELAYS.length) throw error;

            const delay = API_RETRY_DELAYS[attempt];
            console.warn(`${url} failed, retrying in ${delay} ms`, error);
            return new Promise(resolve => setTimeout(resolve, delay))
                .then(() => fetchJson(url, attempt + 1));
        });
}

// One request feeds both the oblast layer and the city markers, so the two
// can never disagree about what is happening.
let threatsRequest = null;

function loadThreats() {
    if (!threatsRequest) threatsRequest = fetchJson(API_URL);
    return threatsRequest;
}

// Redis that holds no state reads as a nationwide all-clear. The server says
// so in meta.state_known, and everything it feeds must show "Немає даних"
// rather than paint the country green.
function stateIsKnown(apiData) {
    return !!apiData && (!apiData.meta || apiData.meta.state_known !== false);
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        API_RETRY_DELAYS,
        fetchJson,
        loadThreats,
        stateIsKnown
    };
}
