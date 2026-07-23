import { useEffect, useState } from "react";

export default function NetworkStatus() {
  const [online, setOnline] = useState(() => navigator.onLine);
  useEffect(() => {
    const sync = () => setOnline(navigator.onLine);
    window.addEventListener("online", sync);
    window.addEventListener("offline", sync);
    return () => { window.removeEventListener("online", sync); window.removeEventListener("offline", sync); };
  }, []);
  return online ? null : <div role="status" className="island-offline-banner">当前处于离线状态：可以浏览已缓存内容，上传与重试将在联网后恢复。</div>;
}
