import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './styles.css'
import './console.css'
import './timeline.css'
import './responsive.css'

const rootElement = document.getElementById('root')

if (rootElement === null) {
  throw new Error('CloudHelm 控制台启动失败：缺少 root 挂载节点。')
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
