// Run with: node --test employee/tests/profile_edit_tabs.test.cjs
// Execute the template's actual tab script without a browser or dependencies.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const template = readFileSync(path.join(__dirname,
    '../templates/employee/profile/profile.html'), 'utf8');
const script = template.match(/<script id="profileEditorTabs">([^]*?)<\/script>/)[1];

function element(id) {
    const classes = new Set();
    return {
        id, hidden: false, attributes: {}, handlers: {},
        dataset: { profileTab: id },
        classList: {
            toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
            contains(name) { return classes.has(name); },
        },
        setAttribute(name, value) { this.attributes[name] = value; },
        addEventListener(name, handler) { this.handlers[name] = handler; },
        click() { assert.fail('Tab activation must not synthesize clicks'); },
    };
}

function setup(savedTab = null, storageBlocked = false) {
    const tabs = ['personal', 'bank'].map(element);
    const panels = ['personal', 'bank'].map(element);
    panels[0].unsavedValue = 'Unsaved personal details';
    const storage = new Map([['staffProfileEditTab', savedTab], ['activeEmpTab', '#work']]);
    const editor = {
        querySelectorAll(selector) {
            if (selector === '[data-profile-tab]') return tabs;
            assert.equal(selector, '.oh-general__tab-target');
            return panels;
        },
    };
    vm.runInNewContext(script, {
        document: {
            getElementById(id) { assert.equal(id, 'profileEditor'); return editor; },
        },
        localStorage: {
            getItem(key) { if (storageBlocked) throw Error('Storage blocked'); return storage.get(key); },
            setItem(key, value) { if (storageBlocked) throw Error('Storage blocked'); storage.set(key, value); },
        },
        // No navigation/network/timer APIs: accessing them fails the test.
    });
    return { tabs, panels, storage };
}

function assertActive(state, name) {
    state.tabs.forEach(tab => {
        assert.equal(tab.attributes['aria-pressed'], String(tab.id === name));
        assert.equal(tab.classList.contains('oh-general__tab-link--active'), tab.id === name);
    });
    state.panels.forEach(panel => {
        assert.equal(panel.hidden, panel.id !== name);
        assert.equal(panel.classList.contains('d-none'), panel.id !== name);
    });
}

test('initial load selects Personal Info without clicking or navigating', () => {
    assertActive(setup(), 'personal');
});

test('restoring Bank Info updates panels without clicking or navigating', () => {
    assertActive(setup('bank'), 'bank');
});

test('invalid or obsolete saved tabs fall back to Personal Info', () => {
    for (const saved of ['work', '#work', '#bank', '[invalid', '']) {
        assertActive(setup(saved), 'personal');
    }
});

test('repeated tab switches do not recurse or discard unsaved input', () => {
    const state = setup();
    for (let i = 0; i < 20; i++) {
        for (const tab of state.tabs) {
            tab.handlers.click();
            assertActive(state, tab.id);
            assert.equal(state.storage.get('staffProfileEditTab'), tab.id);
        }
    }
    assert.equal(state.panels[0].unsavedValue, 'Unsaved personal details');
    assert.equal(state.storage.get('activeEmpTab'), '#work');
});

test('tabs work when browser storage is unavailable', () => {
    const state = setup(null, true);
    assertActive(state, 'personal');
    state.tabs[1].handlers.click();
    assertActive(state, 'bank');
});

test('tab controls cannot navigate, submit forms, or invoke global tab handlers', () => {
    const buttons = template.match(/<button\b[^>]*data-profile-tab="[^"]+"[^>]*>/g);
    assert.equal(buttons.length, 2);
    for (const button of buttons) {
        assert.match(button, /type="button"/);
        assert.doesNotMatch(button, /href=|data-action=|data-target=/);
    }
});
