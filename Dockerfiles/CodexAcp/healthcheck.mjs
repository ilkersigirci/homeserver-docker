#!/usr/bin/env node

fetch("http://127.0.0.1:3021/", {
  signal: AbortSignal.timeout(3000),
}).then(
  (response) => process.exit(response.status === 426 ? 0 : 1),
  () => process.exit(1),
);
