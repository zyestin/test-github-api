const assert = require('assert');
const { sum, multiply, subtract, divide } = require('../src/index.js');

assert.strictEqual(sum(1, 2), 3);
assert.strictEqual(multiply(2, 3), 6);
assert.strictEqual(subtract(10, 4), 6);
assert.strictEqual(divide(10, 2), 5);
assert.throws(() => divide(10, 0), /division by zero/);

console.log('✅ all tests passed');
