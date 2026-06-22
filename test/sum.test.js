const assert = require('assert');
const { sum, multiply } = require('../src/index.js');

// Intentionally wrong expectation to make CI go red
assert.strictEqual(sum(1, 2), 999, 'this will fail on purpose');

console.log('should not reach here');
