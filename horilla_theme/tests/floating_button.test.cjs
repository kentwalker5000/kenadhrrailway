const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const template = readFileSync(path.join(__dirname, '../templates/floating_button.html'), 'utf8');
const script = template.match(/<script>\s*([\s\S]*?)<\/script>/)[1]
    .replace(/{% trans '([^']+)' %}/g, '$1');

function element() {
    const handlers = {};
    const attrs = {};
    const classes = new Set();
    return {
        handlers, attrs, children: [], hidden: false,
        classList: {
            contains: (name) => classes.has(name),
            add: (name) => classes.add(name),
            remove: (name) => classes.delete(name),
            toggle: (name, on) => on ? classes.add(name) : classes.delete(name),
        },
        addEventListener(name, fn) { (handlers[name] ||= []).push(fn); },
        emit(name, event) { for (const fn of handlers[name] || []) fn(event); },
        setAttribute(name, value) { attrs[name] = value; },
        removeAttribute(name) { delete attrs[name]; },
        appendChild(child) { this.children.push(child); },
        append(...children) { this.children.push(...children); },
        replaceChildren() { this.children = []; },
    };
}

function setup() {
    const handlers = {};
    const queue = [];
    const container = element();
    const button = element();
    const status = element();
    const action = element();
    const modal = element();
    const target = element();
    let replayed = 0;
    action.closest = selector => selector === '.inner-fab' ? action : container;
    action.click = () => { replayed++; };
    target.closest = selector => selector === '.oh-modal' ? modal : null;
    container.querySelector = selector => selector === '.main-fab' ? button : status;
    container.querySelectorAll = () => [action];
    container.contains = node => node === action;
    const document = {
        readyState: 'loading',
        getElementById: () => container,
        createElement: () => element(),
        addEventListener(name, fn) { (handlers[name] ||= []).push(fn); },
        emit(name, event = {}) { for (const fn of handlers[name] || []) fn(event); },
    };
    const window = { setTimeout: fn => queue.push(fn) };
    vm.runInNewContext(script, { document, window });
    return { document, window, container, button, status, action, target, modal, queue,
        get replayed() { return replayed; } };
}

test('opens before page ready and replays an early action after HTMX starts', () => {
    const ui = setup();
    ui.button.emit('click', {});
    assert.equal(ui.container.classList.contains('show'), true);
    assert.equal(ui.button.attrs['aria-expanded'], 'true');
    let prevented = false, stopped = false;
    ui.container.emit('click', { target: ui.action, preventDefault() { prevented = true; },
        stopImmediatePropagation() { stopped = true; } });
    assert.ok(prevented && stopped);
    assert.match(ui.status.textContent, /ready/);
    ui.window.htmx = {};
    ui.document.emit('DOMContentLoaded');
    ui.queue.shift()();
    assert.equal(ui.replayed, 1);
    assert.equal(ui.status.hidden, true);
});

test('closing the menu cancels a queued action', () => {
    const ui = setup();
    ui.button.emit('click', {});
    ui.container.emit('click', { target: ui.action, preventDefault() {}, stopImmediatePropagation() {} });
    ui.button.emit('click', {});
    ui.window.htmx = {};
    ui.document.emit('DOMContentLoaded');
    assert.equal(ui.replayed, 0);
    assert.equal(ui.button.attrs['aria-expanded'], 'false');
});

test('a failed request shows retry, and retry invokes the original action', () => {
    const ui = setup();
    const detail = { elt: ui.action, target: ui.target };
    ui.document.emit('htmx:beforeRequest', { detail });
    assert.equal(ui.target.attrs['aria-busy'], 'true');
    assert.equal(ui.modal.classList.contains('oh-modal--show'), true);
    assert.match(ui.target.children[1].children[0].textContent, /Loading/);
    ui.document.emit('htmx:sendError', { detail });
    assert.match(ui.target.children[1].children[0].textContent, /Unable/);
    ui.target.children[1].children[1].emit('click', {});
    assert.equal(ui.replayed, 1);
    ui.document.emit('htmx:afterRequest', { detail });
    assert.equal(ui.target.attrs['aria-busy'], undefined);
});

test('missing HTMX after initialization gives clear feedback', () => {
    const ui = setup();
    ui.document.emit('DOMContentLoaded');
    ui.container.emit('click', { target: ui.action, preventDefault() {}, stopImmediatePropagation() {} });
    assert.match(ui.status.textContent, /refresh/);
    assert.equal(ui.status.hidden, false);
});
