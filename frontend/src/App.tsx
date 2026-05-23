import {useState} from 'react'
import './App.css'
import {useProjectStore} from './store/project'
import MenuBar from './panels/MenuBar'
import ProjectPicker from './panels/ProjectPicker'
import StatsModal from './panels/StatsModal'
import Canvas from './canvas/Canvas'

export default function App() {
  const status = useProjectStore((s) => s.status)
  const [showPicker, setShowPicker] = useState<boolean>(status === 'idle')
  const [showStats, setShowStats] = useState<boolean>(false)

  const handleOpenProject = () => {
    setShowStats(false)
    setShowPicker(true)
  }

  const handlePickerClose = () => {
    setShowPicker(false)
  }

  const handleShowStats = () => {
    setShowStats(true)
  }

  const handleStatsClose = () => {
    setShowStats(false)
  }

  return (
    <div className="app-root">
      <MenuBar onOpenProject={handleOpenProject} onShowStats={handleShowStats} />
      <div className="canvas-host">
        <Canvas />
      </div>
      {showPicker && <ProjectPicker onClose={handlePickerClose} />}
      {showStats && <StatsModal onClose={handleStatsClose} />}
    </div>
  )
}
