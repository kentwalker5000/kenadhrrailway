// Run with: node --test horilla_theme/tests/sidebar_menu.test.cjs
// Exercise the template's actual menu functions without browser dependencies.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const template = readFileSync(path.join(__dirname,
    '../templates/horilla_theme/components/sidebar.html'), 'utf8');
const functions = [
    'setActiveSidebarMenu', 'showFlyout', 'hideFlyout',
    'closeSidebarMenus', 'toggleSidebarMenu', 'syncSidebarToUrl',
    'sidebarLinkMatchScore', 'applySidebarPin', 'syncReferenceToggleLabel',
    'sidebarRequestSource', 'keepSidebarMenuOpenForLink', 'openCurrentSidebarMenu',
].map((name) => {
    const match = template.match(new RegExp(`        function ${name}\\([^]*?\\n        \\}`));
    assert.ok(match, `Template must contain ${name}`);
    return match[0];
}).join('\n');

function element(classes = []) {
    const tokens = new Set(classes);
    const attributes = {};
    return {
        dataset: {},
        classList: {
            contains: (name) => tokens.has(name),
            add: (name) => tokens.add(name),
            remove: (name) => tokens.delete(name),
            toggle(name, force = !tokens.has(name)) {
                if (force) tokens.add(name); else tokens.delete(name);
                return force;
            },
        },
        getAttribute: (name) => attributes[name] ?? null,
        setAttribute: (name, value) => { attributes[name] = value; },
        removeAttribute: (name) => { delete attributes[name]; },
        querySelector: () => null,
        getBoundingClientRect: () => ({ top: 0, right: 72 }),
    };
}

function setup(pinned = true) {
    const menus = ['Employee', 'Payroll', 'Recruitment'].map((name) => {
        const item = element(['sidebar-item']);
        const button = element(['sideboxmain']);
        button.dataset.menu = name;
        button.setAttribute('aria-expanded', 'false');
        const link = element(['sidebar-subnav-link']);
        link.setAttribute('href', `/${name.toLowerCase()}/view/`);
        link.closest = button.closest = () => item;
        const row = { cloneNode: () => ({}) };
        const subnav = {
            querySelector: () => row,
            querySelectorAll: () => [row],
        };
        item.querySelector = (selector) => ({
            '.sidebar-subnav': subnav, '.sideboxmain': button,
        })[selector] ?? null;
        return { item, button, link, subnav };
    });
    const sidebar = element(pinned ? ['sidebar-pinned'] : []);
    const flyout = element();
    const viewport = { matches: false };
    const saved = {};
    const document = {
        getElementById: () => null,
        querySelectorAll(selector) {
            switch (selector) {
                case '.sideboxmain.sidebox-current':
                    return menus.map((m) => m.button).filter((b) => b.classList.contains('sidebox-current'));
                case '#sidebar .sidebar-item.sidebar-open':
                    return menus.map((m) => m.item).filter((i) => i.classList.contains('sidebar-open'));
                case '.sidebar-subnav-link':
                    return menus.map((m) => m.link);
                case 'a.sideboxmain[href]':
                    return [];
                default:
                    throw new Error(`Unexpected selector: ${selector}`);
            }
        },
        querySelector(selector) {
            if (selector === '.oh-main-content') return null;
            if (selector === '.sideboxmain.sidebox-current') {
                return menus.find((m) => m.button.classList.contains('sidebox-current'))?.button ?? null;
            }
            assert.equal(selector, '#sidebar .sidebar-item.sidebar-open .sideboxmain');
            return menus.find((m) => m.item.classList.contains('sidebar-open'))?.button ?? null;
        },
    };
    const context = vm.createContext({
        document,
        sidebarEl: sidebar,
        flyoutEl: flyout,
        flyoutListEl: { innerHTML: '', appendChild() {}, querySelectorAll: () => [] },
        currentFlyoutBtn: null,
        flyoutCloseTimer: null,
        clearTimeout() {},
        positionFlyout() {},
        localStorage: { setItem(key, value) { saved[key] = value; } },
        referenceToggle: null,
        window: { location: { pathname: '/employee/view/' }, matchMedia: () => viewport },
    });
    vm.runInContext(functions, context);
    // The template's first URL sync runs before `sidebarEl` is assigned. Keep
    // that ordering here so accordion tests start from the real initial state.
    context.sidebarEl = null;
    context.syncSidebarToUrl();
    context.sidebarEl = sidebar;
    return {
        menus, context, flyout, sidebar, viewport, saved,
        click: (menu) => context.toggleSidebarMenu(menu.item, menu.button),
    };
}

for (const pinned of [true, false]) {
    const mode = pinned ? 'expanded sidebar' : 'collapsed flyout';

    test(`${mode}: opening each new menu closes and deactivates every sibling`, () => {
        const { menus, click } = setup(pinned);
        for (const selected of [...menus, menus[0]]) {
            click(selected);
            for (const menu of menus) {
                const active = menu === selected;
                assert.equal(menu.button.getAttribute('aria-expanded'), String(active));
                assert.equal(menu.button.classList.contains('sidebox-current'), menu === menus[0]);
                assert.equal(menu.item.classList.contains('sidebar-open'), pinned && active);
            }
        }
    });

    test(`${mode}: clicking the open menu again closes it`, () => {
        const { menus, click, flyout } = setup(pinned);
        click(menus[0]);
        click(menus[0]);
        assert.equal(menus[0].button.getAttribute('aria-expanded'), 'false');
        assert.equal(menus[0].item.classList.contains('sidebar-open'), false);
        assert.equal(flyout.classList.contains('is-visible'), false);
    });

    test(`${mode}: URL updates keep the current module available`, () => {
        const { menus, click, context } = setup(pinned);
        context.syncSidebarToUrl();
        click(menus[1]);
        context.syncSidebarToUrl();
        assert.equal(menus[0].button.classList.contains('sidebox-current'), true);
        assert.equal(menus[1].button.classList.contains('sidebox-current'), false);
        assert.equal(menus[1].button.getAttribute('aria-expanded'), pinned ? 'false' : 'true');
        assert.equal(menus[0].item.classList.contains('sidebar-open'), pinned);
        // The content's current link remains marked as active after navigation.
        assert.equal(menus[0].link.classList.contains('oh-sidebar-active-link'), true);
    });
}

test('opening a menu repairs previously accumulated open siblings', () => {
    const { menus, click } = setup();
    for (const menu of menus) {
        menu.item.classList.add('sidebar-open');
        menu.button.setAttribute('aria-expanded', 'true');
    }
    click(menus[0]);
    assert.ok(menus.every((m) => !m.item.classList.contains('sidebar-open')));
    assert.ok(menus.every((m) => m.button.getAttribute('aria-expanded') === 'false'));
});

test('an empty menu cannot close the currently open menu', () => {
    const { menus, click } = setup();
    click(menus[0]);
    menus[1].subnav.querySelector = () => null;
    click(menus[1]);
    assert.equal(menus[0].item.classList.contains('sidebar-open'), true);
    assert.equal(menus[0].button.classList.contains('sidebox-current'), true);
});

test('selecting a submenu keeps its pinned parent accordion open', () => {
    const { menus, context, click } = setup();
    click(menus[1]);
    context.keepSidebarMenuOpenForLink(menus[1].link);
    assert.equal(menus[1].item.classList.contains('sidebar-open'), true);
    assert.equal(menus[1].button.getAttribute('aria-expanded'), 'true');
    assert.ok(menus.filter((menu) => menu !== menus[1]).every(
        (menu) => !menu.item.classList.contains('sidebar-open'),
    ));
});

test('a full-page navigation reopens the current module in the pinned sidebar', () => {
    const { menus, context } = setup();
    context.openCurrentSidebarMenu();
    assert.equal(menus[0].item.classList.contains('sidebar-open'), true);
    assert.equal(menus[0].button.getAttribute('aria-expanded'), 'true');
});

test('closing a flyout clears its previous owner and accessibility state', () => {
    const { menus, click, context, flyout } = setup(false);
    click(menus[0]);
    context.hideFlyout();
    assert.equal(context.currentFlyoutBtn, null);
    assert.equal(flyout.classList.contains('is-visible'), false);
    assert.equal(menus[0].button.classList.contains('sidebox-active'), false);
    assert.equal(menus[0].button.getAttribute('aria-expanded'), 'false');
});

test('URL updates highlight the current page when no menu is open', () => {
    const { menus, context } = setup();
    context.syncSidebarToUrl();
    assert.equal(menus[0].button.classList.contains('sidebox-current'), true);
    context.window.location.pathname = '/recruitment/view/';
    context.syncSidebarToUrl();
    assert.equal(menus[0].button.classList.contains('sidebox-current'), false);
    assert.equal(menus[2].button.classList.contains('sidebox-current'), true);
});

for (const pinned of [true, false]) {
    test(`closing an unrelated menu preserves the page highlight (pinned=${pinned})`, () => {
        const { menus, context, click } = setup(pinned);
        click(menus[1]);
        click(menus[1]);
        assert.equal(menus[0].button.classList.contains('sidebox-current'), true);
        assert.equal(menus[1].button.classList.contains('sidebox-current'), false);
        context.syncSidebarToUrl();
        assert.equal(menus[0].button.classList.contains('sidebox-current'), true);
    });
}

test('detail route prefixes survive every background URL sync', () => {
    const { menus, context } = setup();
    menus[0].link.dataset.matchPrefixes = '/employee/detail/';
    context.window.location.pathname = '/employee/detail/42/';
    for (let i = 0; i < 3; i++) {
        context.syncSidebarToUrl();
        assert.equal(menus[0].link.getAttribute('aria-current'), 'page');
        assert.equal(menus[0].button.classList.contains('sidebox-current'), true);
    }
});

test('the most specific path wins without matching unrelated path prefixes', () => {
    const { menus, context } = setup();
    menus[1].link.setAttribute('href', '/employee/');
    context.syncSidebarToUrl();
    assert.equal(menus[0].link.getAttribute('aria-current'), 'page');
    assert.equal(menus[1].link.getAttribute('aria-current'), null);
    context.window.location.pathname = '/employee-other/';
    context.syncSidebarToUrl();
    assert.ok(menus.every(m => !m.button.classList.contains('sidebox-current')));
    assert.ok(menus.every(m => m.link.getAttribute('aria-current') === null));
});

test('query strings do not break page matching', () => {
    const { menus, context } = setup();
    menus[0].link.setAttribute('href', '/employee/view/?year=2026');
    context.syncSidebarToUrl();
    assert.equal(menus[0].link.getAttribute('aria-current'), 'page');
});

test('collapsing closes expanded menus and resets accessibility state', () => {
    const { menus, context, sidebar, click } = setup();
    click(menus[1]);
    context.applySidebarPin(false, true);
    assert.equal(sidebar.classList.contains('sidebar-pinned'), false);
    assert.ok(menus.every(m => !m.item.classList.contains('sidebar-open')));
    assert.ok(menus.every(m => m.button.getAttribute('aria-expanded') === 'false'));
    assert.equal(menus[0].button.classList.contains('sidebox-current'), true);
});

test('expanding closes the flyout and clears its owner', () => {
    const { menus, context, flyout, click } = setup(false);
    click(menus[1]);
    context.applySidebarPin(true, true);
    assert.equal(flyout.classList.contains('is-visible'), false);
    assert.equal(context.currentFlyoutBtn, null);
    assert.ok(menus.every(m => m.button.getAttribute('aria-expanded') === 'false'));
});

test('narrow screens use flyouts and preserve the saved desktop preference', () => {
    const { menus, context, sidebar, flyout, viewport, saved, click } = setup();
    click(menus[1]);
    viewport.matches = true;
    context.applySidebarPin(true, false);
    assert.equal(sidebar.classList.contains('sidebar-pinned'), false);
    assert.equal(saved.sidebarPinned, 'true');
    click(menus[1]);
    assert.equal(flyout.classList.contains('is-visible'), true);
    viewport.matches = false;
    context.applySidebarPin(context.sidebarPinned, false);
    assert.equal(sidebar.classList.contains('sidebar-pinned'), true);
    assert.equal(flyout.classList.contains('is-visible'), false);
    assert.ok(menus.every(m => m.button.getAttribute('aria-expanded') === 'false'));
});

test('HTMX owns history without duplicate pushes or unconditional Back/Forward reloads', () => {
    assert.doesNotMatch(template, /window\.history\.pushState/);
    assert.doesNotMatch(template, /window\.onpopstate\s*=/);
    assert.doesNotMatch(template, /addEventListener\("popstate", function.*reload/);
    assert.match(template, /hx-push-url="true"/);
    assert.match(template, /hx-sync="#sidebar:replace"/);
    assert.match(template, /htmx:historyRestore/);
    const historyRestore = template.match(/htmx:historyRestore[\s\S]*?updateSidebarBreadcrumbs\(evt\.detail\.serverResponse\);/);
    assert.ok(historyRestore, 'History restore handler must remain present');
    assert.doesNotMatch(historyRestore[0], /closeSidebarMenus\(\);/);
    const index = readFileSync(path.join(__dirname, '../templates/index.html'), 'utf8');
    assert.match(index, /id="ohMainContent"[^>]*hx-history-elt[^>]*hx-history="false"/);
});

test('navigation fallback identifies the sidebar source when swap events fire on the content', () => {
    const { menus, context } = setup();
    const target = element();
    assert.equal(context.sidebarRequestSource({ detail: {
        elt: target, requestConfig: { elt: menus[0].link },
    } }), menus[0].link);
    assert.equal(context.sidebarRequestSource({ detail: { elt: menus[0].link } }), menus[0].link);
});

test('all inline sidebar scripts compile after rendering template tags', () => {
    for (const match of template.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)) {
        new vm.Script(match[1].replace(/\{%[\s\S]*?%\}/g, '').replace(/\{\{[\s\S]*?\}\}/g, ''));
    }
});
