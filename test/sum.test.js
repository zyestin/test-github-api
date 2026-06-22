const assert = require('assert');
const { sum, multiply, subtract } = require('../src/index.js');

assert.strictEqual(sum(1, 2), 3);
assert.strictEqual(multiply(2, 3), 6);
assert.strictEqual(subtract(10, 4), 6);
assert.strictEqual(subtract(0, 5), -5);

console.log('✅ all tests passed');
