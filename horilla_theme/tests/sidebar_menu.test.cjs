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
    const document = {
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
        localStorage: { setItem() {} },
        window: { location: { pathname: '/employee/view/' } },
    });
    vm.runInContext(functions, context);
    return {
        menus, context, flyout,
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
                assert.equal(menu.button.classList.contains('sidebox-current'), active);
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

    test(`${mode}: background page updates preserve the newly opened menu`, () => {
        const { menus, click, context } = setup(pinned);
        context.syncSidebarToUrl();
        click(menus[1]);
        context.syncSidebarToUrl();
        assert.equal(menus[0].button.classList.contains('sidebox-current'), false);
        assert.equal(menus[1].button.classList.contains('sidebox-current'), true);
        assert.equal(menus[1].button.getAttribute('aria-expanded'), 'true');
        // The content's current link remains marked independently of menu expansion.
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
