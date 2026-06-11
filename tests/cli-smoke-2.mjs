#!/usr/bin/env node

import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const TESTS_DIR = path.dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = path.resolve(TESTS_DIR, '..')
const ACCEPTANCE_SCRIPT = path.join(TESTS_DIR, 'cli-acceptance.mjs')
const FIXTURE = path.join(TESTS_DIR, 'fixtures', '2条冒烟测试集.txt')
const OUTPUT_ROOT = path.join(REPO_ROOT, 'outputs', 'cli-smoke-2')

const args = [
  ACCEPTANCE_SCRIPT,
  '--suite', 'smoke-2',
  '--fixture', FIXTURE,
  '--min-rows', '2',
  '--output-root', OUTPUT_ROOT,
  ...process.argv.slice(2),
]

const child = spawn(process.execPath, args, {
  cwd: REPO_ROOT,
  env: process.env,
  stdio: 'inherit',
  windowsHide: true,
})

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
    return
  }
  process.exit(code ?? 1)
})

child.on('error', (error) => {
  console.error(`启动 2 条冒烟验收失败: ${error.message}`)
  process.exit(1)
})
