import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import { compile, compileModule, preprocess } from 'svelte/compiler';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

const root = new URL('../', import.meta.url);
async function load(relative) {
    const result = await build({ entryPoints: [fileURLToPath(new URL(relative, root))], bundle: true,
        write: false, format: 'esm', platform: 'browser', define: { 'import.meta.env': '{}' } });
    return import('data:text/javascript;base64,' + Buffer.from(result.outputFiles[0].text).toString('base64'));
}
const helpers = await load('src/js/searchRequests.ts');
const api = await load('src/js/stores/api.ts');

test('account selections encode stable user IDs, independent of duplicate names', () => {
    assert.equal(helpers.userSearchToken('from', '000000000000000000000011'), 'from:<@11> ');
    assert.equal(helpers.userSearchToken('mentions', '22'), 'mentions:<@22> ');
    assert.throws(() => helpers.userSearchToken('from', 'alice'));
});

test('request pages remain bounded and preserve every requested ID', () => {
    const ids = Array.from({ length: 251 }, (_, i) => i + 1);
    const pages = helpers.requestBatches(ids);
    assert.deepEqual(pages.map(page => page.length), [100, 100, 51]);
    assert.deepEqual(pages.flat(), ids);
    assert.throws(() => helpers.requestBatches(ids, 0));
});

test('search defaults to the first bounded page with encoded filters', () => {
    const params = helpers.searchParameters('1', 'from:<@11> hello & world');
    assert.equal(params.get('limit'), '50');
    assert.equal(params.get('next_page_cursor'), '0');
    assert.equal(params.get('prompt'), 'from:<@11> hello & world');
    assert.equal(helpers.searchParameters('1', '', 'first', null, 50000).get('limit'), '100');
});

test('directional requests carry exactly one cursor', () => {
    for (const [direction, field] of [['before', 'prev_page_cursor'], ['after', 'next_page_cursor'], ['around', 'around_page_cursor']]) {
        const params = helpers.searchParameters('1', 'from:<@11>', direction, '12', 25);
        assert.equal(params.get(field), '12');
        assert.equal([...params.keys()].filter(key => key.endsWith('_page_cursor')).length, 1);
    }
    assert.throws(() => helpers.searchParameters('1', '', 'around', 'bad'));
});

test('real search API helper sends bounded first-page requests', async () => {
    const previous = globalThis.fetch;
    const calls = [];
    globalThis.fetch = async url => { calls.push(String(url)); return new Response(JSON.stringify({ messageIds: ['1'], messages: [], prevPage: null, nextPage: '1' })); };
    try {
        const page = await api.fetchSearch('1', 'from:<@11>');
        assert.deepEqual(page.messageIds, ['1']);
        const params = new URL(calls[0], 'http://localhost').searchParams;
        assert.equal(params.get('next_page_cursor'), '0');
        assert.equal(params.get('limit'), '50');
        assert.equal(calls.length, 1);
    } finally { globalThis.fetch = previous; }
});

test('media status API batches large requests and removes duplicate IDs', async () => {
    const previous = globalThis.fetch;
    const requests = [];
    globalThis.fetch = async url => {
        const ids = new URL(String(url)).searchParams.get('ids').split(',').map(Number);
        requests.push(ids);
        return new Response(JSON.stringify(ids.map(mediaId => ({ mediaId, status: 'completed' }))));
    };
    try {
        const ids = Array.from({ length: 251 }, (_, i) => i + 1);
        const result = await api.fetchOfflineMediaStatuses([...ids, 1, -1]);
        assert.deepEqual(requests.map(ids => ids.length), [100, 100, 51]);
        assert.deepEqual(result.map(row => row.mediaId), ids);
    } finally { globalThis.fetch = previous; }
});

for (const filename of ['SearchAutoComplete.svelte', 'SearchResults.svelte']) {
    test(`changed Svelte component compiles: ${filename}`, async () => {
        const path = fileURLToPath(new URL('src/lib/search/' + filename, root));
        const source = await readFile(path, 'utf8');
        const processed = await preprocess(source, vitePreprocess(), { filename: path });
        compile(processed.code, { filename: path, generate: 'client' });
    });
}

test('changed search state compiles with Svelte runes', async () => {
    const path = fileURLToPath(new URL('src/lib/search/searchState.svelte.ts', root));
    const result = await build({ entryPoints: [path], bundle: false, write: false, format: 'esm' });
    compileModule(result.outputFiles[0].text, { filename: path.replace('.ts', '.js'), generate: 'client' });
});
