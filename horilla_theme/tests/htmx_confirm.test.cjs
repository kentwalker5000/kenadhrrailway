const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../../static/index/htmxConfirm.js"), "utf8");
const flush = () => new Promise(resolve => setImmediate(resolve));

function harness() {
    const listeners = [];
    const dialogs = [];
    const nativeConfirm = () => true;
    const context = vm.createContext({
        window: { confirm: nativeConfirm },
        document: { addEventListener: (name, handler) => listeners.push({ name, handler }) },
        Swal: { fire: options => new Promise((resolve, reject) => dialogs.push({ options, resolve, reject })) },
        i18nMessages: { confirm: "Confirm", cancel: "Cancel" },
    });
    vm.runInContext(source, context);
    function dispatch(detail, prevented = false) {
        const event = { detail, defaultPrevented: prevented, preventDefault() { this.defaultPrevented = true; } };
        listeners.forEach(({ handler }) => handler(event));
        return event;
    }
    return { context, dialogs, listeners, dispatch, nativeConfirm };
}

test("payslip confirmation resumes the original callback without private element data", async () => {
    const h = harness();
    const requests = [];
    const detail = {
        elt: {}, question: "Send payslip?", path: "/payroll/send-slip/?id=101", verb: "post",
        issueRequest: skip => requests.push({ path: detail.path, verb: detail.verb, skip }),
    };
    assert.equal(h.dispatch(detail).defaultPrevented, true);
    assert.equal(requests.length, 0);
    h.dialogs[0].resolve({ isConfirmed: true });
    await flush();
    assert.deepEqual(requests, [{ path: "/payroll/send-slip/?id=101", verb: "post", skip: true }]);
});

test("cancellation sends nothing", async () => {
    const h = harness();
    let count = 0;
    h.dispatch({ elt: {}, question: "Send?", issueRequest: () => count++ });
    h.dialogs[0].resolve({ isConfirmed: false });
    await flush();
    assert.equal(count, 0);
});

test("requests without a confirmation question are not intercepted", () => {
    const h = harness();
    assert.equal(h.dispatch({ elt: {}, issueRequest() {} }).defaultPrevented, false);
    assert.equal(h.dialogs.length, 0);
});

test("another handler's cancelled request is respected", () => {
    const h = harness();
    h.dispatch({ elt: {}, question: "Send?", issueRequest() {} }, true);
    assert.equal(h.dialogs.length, 0);
});

test("repeated clicks during confirmation only resume one request", async () => {
    const h = harness();
    let count = 0;
    const detail = { elt: {}, question: "Send?", issueRequest: () => count++ };
    h.dispatch(detail);
    h.dispatch(detail);
    assert.equal(h.dialogs.length, 1);
    h.dialogs[0].resolve({ isConfirmed: true });
    await flush();
    assert.equal(count, 1);
});

test("cancelling allows a later deliberate retry", async () => {
    const h = harness();
    const detail = { elt: {}, question: "Send?", issueRequest() {} };
    h.dispatch(detail);
    h.dialogs[0].resolve({ isConfirmed: false });
    await flush();
    h.dispatch(detail);
    assert.equal(h.dialogs.length, 2);
});

test("failed requests are not automatically retried", async () => {
    const h = harness();
    let count = 0;
    h.dispatch({ elt: {}, question: "Send?", issueRequest: () => { count++; return Promise.reject(new Error("failed")); } });
    h.dialogs[0].resolve({ isConfirmed: true });
    await flush();
    assert.equal(count, 1);
});

test("initialization is idempotent and does not replace native confirmation", () => {
    const h = harness();
    vm.runInContext(source, h.context);
    assert.equal(h.listeners.length, 1);
    assert.equal(h.listeners[0].name, "htmx:confirm");
    assert.equal(h.context.window.confirm, h.nativeConfirm);
});
