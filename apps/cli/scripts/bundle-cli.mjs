#!/usr/bin/env node

import { mkdir, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const cliRoot = path.resolve(scriptDir, '..')
const entryPath = path.join(cliRoot, 'bin', 'gen2vec.mjs')
const outPath = path.join(cliRoot, 'dist', 'gen2vec_cli.bundle.cjs')

const importRe = /import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"]\s*;?/g
const modules = new Map()
let importCounter = 0

function toId(filePath) {
  return path.relative(cliRoot, filePath).replace(/\\/g, '/')
}

function resolveLocal(specifier, fromFile) {
  const resolved = path.resolve(path.dirname(fromFile), specifier)
  return path.extname(resolved) ? resolved : `${resolved}.mjs`
}

function parseNamedImports(specifier) {
  return specifier
    .replace(/^\{|\}$/g, '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [name, alias] = part.split(/\s+as\s+/)
      return { name: name.trim(), alias: (alias || name).trim() }
    })
}

function buildImportReplacement(imported, specifier, fromFile) {
  const isLocal = specifier.startsWith('.') || specifier.startsWith('/')
  const requireExpr = isLocal
    ? `__localRequire(${JSON.stringify(toId(resolveLocal(specifier, fromFile)))})`
    : `__nodeRequire(${JSON.stringify(specifier)})`
  const cleaned = imported.trim()
  const tempName = () => `__import_${importCounter++}`

  if (cleaned.startsWith('{')) {
    const binding = tempName()
    const declarations = parseNamedImports(cleaned)
      .map(({ name, alias }) => (name === alias ? `const ${name} = ${binding}.${name};` : `const ${alias} = ${binding}.${name};`))
      .join('\n')
    return `const ${binding} = ${requireExpr};\n${declarations}\n`
  }

  if (cleaned.includes(',')) {
    const [defaultName, namedPart] = cleaned.split(/,(.+)/).map((part) => part.trim()).filter(Boolean)
    const binding = tempName()
    const declarations = parseNamedImports(namedPart)
      .map(({ name, alias }) => (name === alias ? `const ${name} = ${binding}.${name};` : `const ${alias} = ${binding}.${name};`))
      .join('\n')
    return `const ${binding} = ${requireExpr};\nconst ${defaultName} = __importDefault(${binding});\n${declarations}\n`
  }

  return `const ${cleaned} = __importDefault(${requireExpr});\n`
}

async function collect(filePath) {
  const absolutePath = path.resolve(filePath)
  const id = toId(absolutePath)
  if (modules.has(id)) return

  const source = await readFile(absolutePath, 'utf8')
  modules.set(id, { filePath: absolutePath, source })

  for (const match of source.matchAll(importRe)) {
    const specifier = match[2]
    if (specifier.startsWith('.') || specifier.startsWith('/')) {
      await collect(resolveLocal(specifier, absolutePath))
    }
  }
}

function transformModule({ filePath, source }) {
  const exports = []
  let code = source.replace(/^#!.*\r?\n/, '')

  code = code.replace(importRe, (match, imported, specifier) => buildImportReplacement(imported, specifier, filePath))

  code = code.replace(/\bexport\s+async\s+function\s+([A-Za-z_$][\w$]*)/g, (_, name) => {
    exports.push(name)
    return `async function ${name}`
  })
  code = code.replace(/\bexport\s+function\s+([A-Za-z_$][\w$]*)/g, (_, name) => {
    exports.push(name)
    return `function ${name}`
  })
  code = code.replace(/\bexport\s+const\s+([A-Za-z_$][\w$]*)\s*=/g, (_, name) => {
    exports.push(name)
    return `const ${name} =`
  })

  const exportLines = [...new Set(exports)].map((name) => `__exports.${name} = ${name}`).join('\n')
  return `${code}\n${exportLines}\n`
}

await collect(entryPath)
await mkdir(path.dirname(outPath), { recursive: true })

const chunks = []
chunks.push(`#!/usr/bin/env node
'use strict'

const __nodeRequire = require
const __modules = new Map()
const __cache = new Map()

function __define(id, factory) {
  __modules.set(id, factory)
}

function __importDefault(value) {
  return value && value.__esModule && Object.prototype.hasOwnProperty.call(value, 'default') ? value.default : value
}

function __require(id) {
  if (__cache.has(id)) return __cache.get(id).exports
  const factory = __modules.get(id)
  if (!factory) throw new Error('Bundled module not found: ' + id)
  const module = { exports: {} }
  __cache.set(id, module)
  factory(__require, module, module.exports)
  return module.exports
}
`)

for (const [id, mod] of modules) {
  chunks.push(`\n__define(${JSON.stringify(id)}, function(__localRequire, __module, __exports) {\n${transformModule(mod)}\n})\n`)
}

chunks.push(`\n__require(${JSON.stringify(toId(entryPath))})\n`)

await writeFile(outPath, chunks.join(''), 'utf8')
console.log(`Bundled CLI: ${outPath}`)
