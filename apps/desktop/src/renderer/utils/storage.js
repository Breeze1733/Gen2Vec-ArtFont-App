/**
 * 历史结果持久化工具
 * - IndexedDB 存储完整结果数据（base64 图片可达数 MB，localStorage 容量不足）
 * - localStorage 仅存储任务元信息 + 缩略图
 */

const DB_NAME = 'art-text-results'
const DB_VERSION = 1
const STORE_NAME = 'results'

let dbInstance = null

function openDB() {
  if (dbInstance) return Promise.resolve(dbInstance)

  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION)

    request.onupgradeneeded = (event) => {
      const db = event.target.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id' })
      }
    }

    request.onsuccess = (event) => {
      dbInstance = event.target.result
      resolve(dbInstance)
    }

    request.onerror = () => {
      reject(request.error)
    }
  })
}

/**
 * 保存任务结果到 IndexedDB
 * @param {number|string} id - 任务 ID
 * @param {Object} resultData - { original, transparent, preview, svg, metadata }
 */
export async function saveResultToDB(id, resultData) {
  try {
    const db = await openDB()
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    store.put({ id, ...resultData })
    return new Promise((resolve, reject) => {
      tx.oncomplete = resolve
      tx.onerror = () => reject(tx.error)
    })
  } catch (err) {
    console.warn('IndexedDB 保存失败:', err)
  }
}

/**
 * 从 IndexedDB 读取任务结果
 * @param {number|string} id
 * @returns {Promise<Object|null>}
 */
export async function loadResultFromDB(id) {
  try {
    const db = await openDB()
    const tx = db.transaction(STORE_NAME, 'readonly')
    const store = tx.objectStore(STORE_NAME)
    const request = store.get(id)
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result || null)
      request.onerror = () => reject(request.error)
    })
  } catch (err) {
    console.warn('IndexedDB 读取失败:', err)
    return null
  }
}

/**
 * 从 IndexedDB 删除任务结果
 * @param {number|string} id
 */
export async function deleteResultFromDB(id) {
  try {
    const db = await openDB()
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    store.delete(id)
    return new Promise((resolve, reject) => {
      tx.oncomplete = resolve
      tx.onerror = () => reject(tx.error)
    })
  } catch (err) {
    console.warn('IndexedDB 删除失败:', err)
  }
}

/**
 * 清理 IndexedDB 中超出历史记录范围的旧数据
 * @param {Array<number|string>} validIds - 当前历史记录中保留的 ID 列表
 */
export async function cleanupResults(validIds) {
  try {
    const db = await openDB()
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    const request = store.getAllKeys()
    return new Promise((resolve, reject) => {
      request.onsuccess = () => {
        const validSet = new Set(validIds)
        const keys = request.result
        for (const key of keys) {
          if (!validSet.has(key)) {
            store.delete(key)
          }
        }
        resolve()
      }
      request.onerror = () => reject(request.error)
    })
  } catch (err) {
    console.warn('IndexedDB 清理失败:', err)
  }
}

/**
 * 从 data URL 生成缩略图（宽度 64px，保持比例）
 * @param {string} dataUrl - 原始 data URL
 * @returns {Promise<string>} 缩略图 data URL
 */
export function makeThumbnail(dataUrl) {
  return new Promise((resolve) => {
    if (!dataUrl) return resolve('')

    const img = new Image()
    img.onload = () => {
      const targetW = 64
      const ratio = targetW / img.width
      const targetH = Math.round(img.height * ratio)

      const canvas = document.createElement('canvas')
      canvas.width = targetW
      canvas.height = targetH
      const ctx = canvas.getContext('2d')
      ctx.drawImage(img, 0, 0, targetW, targetH)

      try {
        resolve(canvas.toDataURL('image/jpeg', 0.6))
      } catch {
        resolve('')
      }
    }
    img.onerror = () => resolve('')
    img.src = dataUrl
  })
}
