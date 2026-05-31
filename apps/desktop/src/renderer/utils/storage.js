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
      // 监听连接意外关闭，清除缓存以便下次重新打开
      dbInstance.onclose = () => { dbInstance = null }
      resolve(dbInstance)
    }

    request.onerror = () => {
      console.error('IndexedDB 打开失败:', request.error)
      reject(request.error)
    }
  })
}

/**
 * 保存任务结果到 IndexedDB
 * @param {number|string} id - 任务 ID
 * @param {Object} resultData - { original, transparent, preview, svg, metadata }
 * @returns {Promise<boolean>} 是否保存成功
 */
export async function saveResultToDB(id, resultData) {
  try {
    const db = await openDB()
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    const record = { id, ...resultData }
    store.put(record)

    return new Promise((resolve) => {
      tx.oncomplete = () => {
        console.log('[storage] 结果已保存到 IndexedDB, id:', id)
        resolve(true)
      }
      tx.onerror = () => {
        console.error('[storage] IndexedDB 保存事务失败:', tx.error)
        resolve(false)
      }
      tx.onabort = () => {
        console.error('[storage] IndexedDB 保存事务中止:', tx.error)
        resolve(false)
      }
    })
  } catch (err) {
    console.error('[storage] IndexedDB 保存异常:', err)
    return false
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
    return new Promise((resolve) => {
      request.onsuccess = () => {
        const result = request.result || null
        console.log('[storage] IndexedDB 读取 id:', id, result ? '✓ 有数据' : '✗ 无数据')
        resolve(result)
      }
      request.onerror = () => {
        console.error('[storage] IndexedDB 读取失败:', request.error)
        resolve(null)
      }
    })
  } catch (err) {
    console.error('[storage] IndexedDB 读取异常:', err)
    return null
  }
}

/**
 * 从 IndexedDB 删除任务结果
 * @param {number|string} id
 * @returns {Promise<boolean>}
 */
export async function deleteResultFromDB(id) {
  try {
    const db = await openDB()
    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    store.delete(id)
    return new Promise((resolve) => {
      tx.oncomplete = () => resolve(true)
      tx.onerror = () => { console.error('[storage] 删除失败:', tx.error); resolve(false) }
    })
  } catch (err) {
    console.error('[storage] IndexedDB 删除异常:', err)
    return false
  }
}

/**
 * 清理 IndexedDB 中不在 validIds 列表中的旧数据
 * 使用独立连接，避免与正在进行的保存事务冲突
 * @param {Array<number|string>} validIds - 当前历史记录中保留的 ID 列表
 * @returns {Promise<boolean>}
 */
export async function cleanupResults(validIds) {
  // 每次清理用独立连接，避免复用正在写入的连接导致事务冲突
  let db = null
  try {
    db = await new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION)
      req.onsuccess = () => resolve(req.result)
      req.onerror = () => reject(req.error)
    })

    const tx = db.transaction(STORE_NAME, 'readwrite')
    const store = tx.objectStore(STORE_NAME)
    const getAllReq = store.getAllKeys()

    return new Promise((resolve) => {
      getAllReq.onsuccess = () => {
        const validSet = new Set(validIds)
        const keys = getAllReq.result
        let deleted = 0
        for (const key of keys) {
          if (!validSet.has(key)) {
            store.delete(key)
            deleted++
          }
        }
        if (deleted > 0) {
          console.log(`[storage] 清理了 ${deleted} 条过期 IndexedDB 记录`)
        }
      }
      tx.oncomplete = () => resolve(true)
      tx.onerror = () => { console.warn('[storage] 清理事务失败:', tx.error); resolve(false) }
    })
  } catch (err) {
    console.warn('[storage] IndexedDB 清理异常:', err)
    return false
  } finally {
    // 关闭独立连接
    if (db) db.close()
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
