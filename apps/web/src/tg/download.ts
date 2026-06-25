// 出图下载闸门：下载前先看广告解锁，解锁后同会话内复用。
// 全部出图页共用，避免在各页重复粘贴广告倒计时逻辑。
import { ref } from 'vue'

// 触发一次浏览器下载（data URI / blob URL 均可）。返回是否成功。
export function downloadImage(src: string, filename: string): boolean {
  try {
    const a = document.createElement('a')
    a.href = src
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    return true
  } catch {
    return false
  }
}

// 看广告解锁下载的闸门。首次下载弹广告倒计时，倒计时结束领取后才真正下载；
// 同一会话解锁一次后，后续下载直接放行。
export function useDownloadGate(adSeconds = 30) {
  const adVisible = ref(false)
  const adRemain = ref(0)
  const unlocked = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null
  let pending: (() => void) | null = null

  // download：真正执行下载的回调（解锁后调用）。
  function requestDownload(download: () => void) {
    if (unlocked.value) { download(); return }
    pending = download
    adVisible.value = true
    adRemain.value = adSeconds
    if (timer) clearInterval(timer)
    timer = setInterval(() => {
      adRemain.value--
      if (adRemain.value <= 0 && timer) { clearInterval(timer); timer = null }
    }, 1000)
  }

  // 广告结束后用户点「领取并下载」。
  function claim() {
    if (adRemain.value > 0) return
    unlocked.value = true
    adVisible.value = false
    const fn = pending
    pending = null
    fn?.()
  }

  return { adVisible, adRemain, unlocked, requestDownload, claim }
}
