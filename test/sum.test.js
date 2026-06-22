const assert = require('assert');
const { sum } = require('../src/index.js');

assert.strictEqual(sum(1, 2), 3, '1 + 2 should be 3');
assert.strictEqual(sum(-1, 1), 0, '-1 + 1 should be 0');
assert.strictEqual(sum(0, 0), 0, '0 + 0 should be 0');

console.log('✅ all tests passed');
