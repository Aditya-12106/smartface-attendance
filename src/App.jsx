import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import {
  apiRegisterStudent,
  apiListStudents,
  apiMarkAttendance,
  apiAttendanceToday,
  apiAttendanceMatrix,
  apiExportGroupExcelUrl,
  apiExportAll,
  apiImportAll,
} from './api'

const FACE_THRESHOLD = 0.52
const SCAN_INTERVAL_MS = 1500

const MODEL_URLS = [
  'https://justadudewhohacks.github.io/face-api.js/models',
  'https://raw.githubusercontent.com/justadudewhohacks/face-api.js/master/weights',
]

const FACE_API_SOURCES = [
  'https://cdn.jsdelivr.net/npm/face-api.js@0.22.2/dist/face-api.min.js',
  'https://unpkg.com/face-api.js@0.22.2/dist/face-api.min.js',
]

function safeGroupName(groupName) {
  const cleaned = (groupName || '').trim()
  return cleaned || 'Unassigned'
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function euclidean(a, b) {
  let sum = 0
  for (let i = 0; i < a.length; i += 1) {
    const diff = a[i] - b[i]
    sum += diff * diff
  }
  return Math.sqrt(sum)
}

function formatTimestampLabel(ts) {
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return String(ts)
  return date.toLocaleDateString()
}

function App() {
  // Students and attendance now live in the database - these are just a
  // client-side cache, refreshed from the API on load and after writes.
  const [students, setStudents] = useState([])
  const [attendance, setAttendance] = useState([])
  const [dataStatus, setDataStatus] = useState('')

  const [studentName, setStudentName] = useState('')
  const [studentGroup, setStudentGroup] = useState('')
  const [studentPhoto, setStudentPhoto] = useState(null)
  const [groupPhoto, setGroupPhoto] = useState(null)
  const [groupScopeName, setGroupScopeName] = useState('')

  const [filterGroup, setFilterGroup] = useState('')
  const [selectedGroupView, setSelectedGroupView] = useState('')
  const [selectedGroupSheet, setSelectedGroupSheet] = useState({ timestamps: [], rows: [] })

  const [modelsReady, setModelsReady] = useState(false)
  const [modelStatus, setModelStatus] = useState('Loading AI models...')
  const [registerStatus, setRegisterStatus] = useState('')
  const [groupStatus, setGroupStatus] = useState('')
  const [datasetStatus, setDatasetStatus] = useState('')
  const [datasetPreview, setDatasetPreview] = useState(null)
  const [isImportingDataset, setIsImportingDataset] = useState(false)
  const [cameraStatus, setCameraStatus] = useState('Camera is currently offline.')
  const [processedPreview, setProcessedPreview] = useState('')

  const [isCameraOn, setIsCameraOn] = useState(false)
  const [isCapturingRegister, setIsCapturingRegister] = useState(false)

  const videoRef = useRef(null)
  const overlayRef = useRef(null)
  const streamRef = useRef(null)
  const scannerTimerRef = useRef(null)
  const datasetFileInputRef = useRef(null)

  const filteredAttendance = useMemo(() => {
    const g = filterGroup.trim().toLowerCase()
    if (!g) return attendance
    return attendance.filter((r) => (r.group || '').toLowerCase() === g)
  }, [attendance, filterGroup])

  const knownGroups = useMemo(() => {
    const groups = new Set()
    students.forEach((s) => {
      if (s.group) groups.add(s.group)
    })
    return Array.from(groups).sort((a, b) => a.localeCompare(b))
  }, [students])

  // Load students + today's attendance from the backend on first render.
  async function refreshFromServer() {
    try {
      const [studentList, attendanceList] = await Promise.all([
        apiListStudents(),
        apiAttendanceToday(),
      ])
      setStudents(studentList)
      setAttendance(attendanceList)
      setDataStatus('')
    } catch (err) {
      setDataStatus(
        `Could not reach the backend at http://127.0.0.1:8000 - is it running? (${err.message})`,
      )
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- standard fetch-on-mount
    refreshFromServer()
  }, [])

  useEffect(() => {
    let mounted = true

    async function bootModels() {
      try {
        await loadFaceApiLibrary()
        await loadModelsFromAnyCdn()
        if (!mounted) return
        setModelsReady(true)
        setModelStatus('AI Ready')
      } catch (err) {
        if (!mounted) return
        setModelStatus('Model load failed')
        setCameraStatus(`Failed to load models: ${err.message}`)
      }
    }

    bootModels()

    return () => {
      mounted = false
      stopCamera()
    }
  }, [])

  // Fetch the present/absent matrix for whichever group is selected.
  useEffect(() => {
    if (!selectedGroupView) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- resetting on selection change
      setSelectedGroupSheet({ timestamps: [], rows: [] })
      return
    }
    apiAttendanceMatrix(selectedGroupView)
      .then(setSelectedGroupSheet)
      .catch((err) => setGroupStatus(`Could not load matrix: ${err.message}`))
  }, [selectedGroupView, attendance])

  function getFaceApi() {
    if (!window.faceapi) {
      throw new Error('face-api.js not loaded.')
    }
    return window.faceapi
  }

  async function loadFaceApiLibrary() {
    if (window.faceapi) return

    for (const src of FACE_API_SOURCES) {
      try {
        // eslint-disable-next-line no-await-in-loop
        await new Promise((resolve, reject) => {
          const script = document.createElement('script')
          script.src = src
          script.async = true
          script.onload = resolve
          script.onerror = reject
          document.head.appendChild(script)
        })
        if (window.faceapi) return
      } catch {
        // try next source
      }
    }

    throw new Error('Unable to load face-api library from CDN.')
  }

  async function loadModelsFromAnyCdn() {
    const faceapi = getFaceApi()
    let lastError = new Error('Model load failed')

    for (const url of MODEL_URLS) {
      try {
        // eslint-disable-next-line no-await-in-loop
        await faceapi.nets.tinyFaceDetector.loadFromUri(url)
        // eslint-disable-next-line no-await-in-loop
        await faceapi.nets.faceLandmark68Net.loadFromUri(url)
        // eslint-disable-next-line no-await-in-loop
        await faceapi.nets.faceRecognitionNet.loadFromUri(url)
        return
      } catch (err) {
        lastError = err
      }
    }

    throw lastError
  }

  async function ensureCamera() {
    if (streamRef.current) return
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
    streamRef.current = stream
    videoRef.current.srcObject = stream
    await videoRef.current.play()
    syncOverlaySize()
    setIsCameraOn(true)
    setCameraStatus('Camera started. Ready to scan.')
  }

  function stopCamera() {
    if (scannerTimerRef.current) {
      clearInterval(scannerTimerRef.current)
      scannerTimerRef.current = null
    }

    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }

    if (videoRef.current) {
      videoRef.current.srcObject = null
    }

    clearOverlay()
    setIsCameraOn(false)
    setCameraStatus('Camera is currently offline.')
  }

  function clearOverlay() {
    const canvas = overlayRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)
  }

  function syncOverlaySize() {
    if (!videoRef.current || !overlayRef.current) return
    if (!videoRef.current.videoWidth || !videoRef.current.videoHeight) return

    const canvas = overlayRef.current
    canvas.width = videoRef.current.videoWidth
    canvas.height = videoRef.current.videoHeight
    canvas.style.width = `${videoRef.current.clientWidth}px`
    canvas.style.height = `${videoRef.current.clientHeight}px`
  }

  // Matching still happens entirely client-side against descriptors the
  // backend handed back with the student list.
  function matchDescriptor(descriptor, groupFilter = '') {
    const normalizedGroup = groupFilter.trim().toLowerCase()
    let best = { id: null, name: 'Unknown', group: '', distance: 999 }

    students.forEach((student) => {
      if (normalizedGroup && (student.group || '').toLowerCase() !== normalizedGroup) return
      ;(student.descriptors || []).forEach((desc) => {
        const d = euclidean(descriptor, desc)
        if (d < best.distance) {
          best = { id: student.id, name: student.name, group: student.group || '', distance: d }
        }
      })
    })

    if (best.distance <= FACE_THRESHOLD) return best
    return { id: null, name: 'Unknown', group: '', distance: best.distance }
  }

  // Marks attendance via the API. The database itself rejects a duplicate
  // for today, so this is safe to call repeatedly from the scan loop.
  async function markAttendance(studentId, name, group) {
    if (!studentId) return
    try {
      const result = await apiMarkAttendance(studentId)
      if (!result.alreadyMarked) {
        setAttendance((prev) => [
          ...prev,
          {
            id: result.record.id,
            student_id: studentId,
            name,
            group: group || '',
            date: result.record.date,
            time: result.record.time,
          },
        ])
      }
    } catch (err) {
      setCameraStatus(`Could not save attendance: ${err.message}`)
    }
  }

  async function exportGroupExcel(groupName) {
    const group = safeGroupName(groupName)
    // Backend generates the workbook on demand from the database, so the
    // download is always the current source of truth, not a stale copy.
    window.open(apiExportGroupExcelUrl(group), '_blank')
    setGroupStatus(`Requested Excel download for ${group}.`)
  }

  async function exportDataset() {
    try {
      const dump = await apiExportAll()
      const blob = new Blob([JSON.stringify(dump, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `smartface_dataset_${new Date().toISOString().replace(/[:.]/g, '-')}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      setDatasetStatus('Dataset exported successfully.')
    } catch (err) {
      setDatasetStatus(`Export failed: ${err.message}`)
    }
  }

  function inspectDatasetForPreview(data, fileName) {
    if (!data || typeof data !== 'object' || Array.isArray(data) || !Array.isArray(data.students)) {
      throw new Error('This file is not a SmartFace dataset. Expected a JSON object with a students list.')
    }

    const isLegacy = Boolean(data.attendanceByDate || data.groupSheets)
    if (isLegacy) {
      if ((data.attendanceByDate && (typeof data.attendanceByDate !== 'object' || Array.isArray(data.attendanceByDate))) ||
          (data.groupSheets && (typeof data.groupSheets !== 'object' || Array.isArray(data.groupSheets)))) {
        throw new Error('The legacy dataset has an invalid attendance or group-sheet section.')
      }
    } else if (data.attendance !== undefined && !Array.isArray(data.attendance)) {
      throw new Error('The dataset attendance field must be a list.')
    }

    const descriptorCount = data.students.reduce((total, student) => {
      return total + (Array.isArray(student?.descriptors) ? student.descriptors.length : 0)
    }, 0)

    const attendanceKeys = new Set()
    if (isLegacy) {
      Object.entries(data.attendanceByDate || {}).forEach(([date, records]) => {
        if (Array.isArray(records)) {
          records.forEach((record) => {
            const status = String(record?.Status ?? record?.status ?? 'Present').toLowerCase()
            if (['present', 'p', ''].includes(status)) {
              attendanceKeys.add(`${String(date).slice(0, 10)}|${record?.Name ?? record?.name ?? ''}|${String(record?.Group ?? record?.group ?? '').toLowerCase() === 'unassigned' ? '' : (record?.Group ?? record?.group ?? '')}`)
            }
          })
        }
      })
      Object.entries(data.groupSheets || {}).forEach(([group, sheet]) => {
        const timestamps = Array.isArray(sheet?.timestamps) ? sheet.timestamps : []
        ;(Array.isArray(sheet?.rows) ? sheet.rows : []).forEach((row) => {
          timestamps.forEach((date) => {
            const status = String(row?.[date] ?? 'a').toLowerCase()
            if (status === 'p' || status === 'present') {
              attendanceKeys.add(`${String(date).slice(0, 10)}|${row?.Name ?? row?.name ?? ''}|${group.toLowerCase() === 'unassigned' ? '' : group}`)
            }
          })
        })
      })
    } else {
      ;(Array.isArray(data.attendance) ? data.attendance : []).forEach((record) => {
        attendanceKeys.add(`${String(record?.date ?? '').slice(0, 10)}|${record?.student_id ?? ''}`)
      })
    }

    const sessionCount = isLegacy
      ? Object.values(data.groupSheets || {}).reduce((total, sheet) => total + (Array.isArray(sheet?.timestamps) ? sheet.timestamps.length : 0), 0)
      : (Array.isArray(data.attendance_sessions) ? data.attendance_sessions.length : 0)

    return {
      fileName,
      data,
      format: isLegacy ? 'Legacy browser backup' : 'SmartFace API backup',
      studentCount: data.students.length,
      descriptorCount,
      attendanceCount: attendanceKeys.size,
      sessionCount,
    }
  }

  async function handleDatasetFileSelected(event) {
    const file = event.target.files?.[0]
    if (!file) return

    setDatasetStatus('Reading dataset...')
    setDatasetPreview(null)
    try {
      const parsed = JSON.parse(await file.text())
      const preview = inspectDatasetForPreview(parsed, file.name)
      setDatasetPreview(preview)
      setDatasetStatus('Dataset validated. Review the summary before importing.')
    } catch (err) {
      setDatasetStatus(`Import preparation failed: ${err.message}`)
    } finally {
      // Reset so selecting the same file again triggers onChange.
      event.target.value = ''
    }
  }

  async function importDataset() {
    if (!datasetPreview || isImportingDataset) return

    setIsImportingDataset(true)
    setDatasetStatus('Importing and merging dataset into the database...')
    try {
      const result = await apiImportAll(datasetPreview.data)
      await refreshFromServer()
      setSelectedGroupView('')
      setDatasetPreview(null)
      setDatasetStatus(
        `Import complete: ${result.students_added} new students, ${result.students_merged} existing students merged, ` +
        `${result.descriptors_added} new face samples, ${result.attendance_added} attendance records added, ` +
        `${result.attendance_skipped} duplicate attendance records skipped.`,
      )
    } catch (err) {
      setDatasetStatus(`Dataset import failed: ${err.message}`)
    } finally {
      setIsImportingDataset(false)
    }
  }

  function cancelDatasetImport() {
    setDatasetPreview(null)
    setDatasetStatus('Dataset import cancelled.')
    if (datasetFileInputRef.current) datasetFileInputRef.current.value = ''
  }

  async function descriptorFromImageElement(imageEl) {
    const faceapi = getFaceApi()
    const detection = await faceapi
      .detectSingleFace(imageEl, new faceapi.TinyFaceDetectorOptions())
      .withFaceLandmarks()
      .withFaceDescriptor()

    if (!detection) return null
    return Array.from(detection.descriptor)
  }

  async function descriptorFromCurrentVideoFrame() {
    const faceapi = getFaceApi()
    const detection = await faceapi
      .detectSingleFace(videoRef.current, new faceapi.TinyFaceDetectorOptions())
      .withFaceLandmarks()
      .withFaceDescriptor()

    if (!detection) return null
    return Array.from(detection.descriptor)
  }

  // Registers with the backend and merges the returned student (with its
  // full descriptor list) into local state.
  async function addStudentSamples(name, group, descriptors) {
    const finalName = name.trim()
    const finalGroup = group.trim()
    const savedStudent = await apiRegisterStudent(finalName, finalGroup, descriptors)

    setStudents((prev) => {
      const withoutOld = prev.filter((s) => s.id !== savedStudent.id)
      return [...withoutOld, savedStudent]
    })
  }

  async function handleRegisterSubmit(event) {
    event.preventDefault()

    if (!modelsReady) {
      setRegisterStatus('Models are still loading. Please wait.')
      return
    }

    const name = studentName.trim()
    if (!name) {
      setRegisterStatus('Enter name before registration.')
      return
    }

    if (!studentPhoto) {
      await captureEightSamples()
      return
    }

    try {
      const imageURL = URL.createObjectURL(studentPhoto)
      const imageEl = new Image()
      imageEl.src = imageURL
      await imageEl.decode()
      const descriptor = await descriptorFromImageElement(imageEl)
      URL.revokeObjectURL(imageURL)

      if (!descriptor) {
        setRegisterStatus('No clear face detected in uploaded image.')
        return
      }

      await addStudentSamples(name, studentGroup, [descriptor])
      setRegisterStatus(`Registered ${name} successfully.`)
      setStudentPhoto(null)
    } catch (err) {
      setRegisterStatus(`Registration failed: ${err.message}`)
    }
  }

  async function captureEightSamples() {
    if (!modelsReady) {
      setRegisterStatus('Models are still loading. Please wait.')
      return
    }

    const name = studentName.trim()
    if (!name) {
      setRegisterStatus('Enter student name before capture.')
      return
    }

    setIsCapturingRegister(true)
    try {
      await ensureCamera()
      const samples = []
      let attempts = 0

      while (samples.length < 8 && attempts < 32) {
        attempts += 1
        // eslint-disable-next-line no-await-in-loop
        const descriptor = await descriptorFromCurrentVideoFrame()
        if (descriptor) {
          samples.push(descriptor)
          setRegisterStatus(`Captured ${samples.length}/8 face samples...`)
        }
        // eslint-disable-next-line no-await-in-loop
        await sleep(320)
      }

      if (samples.length < 7) {
        setRegisterStatus(`Only ${samples.length} captures detected. Try again with better light.`)
        return
      }

      await addStudentSamples(name, studentGroup, samples)
      setRegisterStatus(`Registered ${name} with ${samples.length} camera samples.`)
    } catch (err) {
      setRegisterStatus(`Capture failed: ${err.message}`)
    } finally {
      setIsCapturingRegister(false)
    }
  }

  async function processLiveFrame() {
    const faceapi = getFaceApi()
    const detections = await faceapi
      .detectAllFaces(videoRef.current, new faceapi.TinyFaceDetectorOptions())
      .withFaceLandmarks()
      .withFaceDescriptors()

    syncOverlaySize()

    const canvas = overlayRef.current
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    const recognizedNow = []
    detections.forEach((det) => {
      const match = matchDescriptor(Array.from(det.descriptor), filterGroup)
      const known = match.name !== 'Unknown'
      const box = det.detection.box

      if (known) {
        markAttendance(match.id, match.name, match.group)
        recognizedNow.push(match.name)
      }

      ctx.strokeStyle = known ? '#0f9f6f' : '#dc2626'
      ctx.lineWidth = 3
      ctx.strokeRect(box.x, box.y, box.width, box.height)

      ctx.fillStyle = known ? '#0f9f6f' : '#dc2626'
      ctx.fillRect(box.x, box.y + box.height - 22, box.width, 22)

      ctx.fillStyle = '#ffffff'
      ctx.font = '13px Poppins, sans-serif'
      ctx.fillText(known ? match.name : 'Unknown', box.x + 5, box.y + box.height - 7)
    })

    setCameraStatus(recognizedNow.length ? `Live recognized: ${recognizedNow.join(', ')}` : 'Live recognized: none')
  }

  async function startLiveScanner() {
    if (!modelsReady) {
      setCameraStatus('Models are still loading. Please wait.')
      return
    }

    try {
      await ensureCamera()
      if (scannerTimerRef.current) clearInterval(scannerTimerRef.current)
      scannerTimerRef.current = setInterval(() => {
        processLiveFrame().catch((err) => setCameraStatus(`Scan error: ${err.message}`))
      }, SCAN_INTERVAL_MS)
      setCameraStatus('Live scanner started.')
    } catch (err) {
      setCameraStatus(`Camera access failed: ${err.message}`)
    }
  }

  async function handleGroupPhotoSubmit(event) {
    event.preventDefault()

    if (!modelsReady) {
      setGroupStatus('Models are still loading. Please wait.')
      return
    }

    if (!groupPhoto) {
      setGroupStatus('Upload a classroom photo first.')
      return
    }

    const group = safeGroupName(groupScopeName)
    const faceapi = getFaceApi()

    try {
      const imageURL = URL.createObjectURL(groupPhoto)
      const imageEl = new Image()
      imageEl.src = imageURL
      await imageEl.decode()

      const detections = await faceapi
        .detectAllFaces(imageEl, new faceapi.TinyFaceDetectorOptions())
        .withFaceLandmarks()
        .withFaceDescriptors()

      const canvas = document.createElement('canvas')
      canvas.width = imageEl.width
      canvas.height = imageEl.height
      const ctx = canvas.getContext('2d')
      ctx.drawImage(imageEl, 0, 0)

      const recognized = []
      let unknown = 0

      for (const det of detections) {
        const match = matchDescriptor(Array.from(det.descriptor), group)
        const known = match.name !== 'Unknown'
        const box = det.detection.box

        if (known) {
          // eslint-disable-next-line no-await-in-loop
          await markAttendance(match.id, match.name, match.group)
          recognized.push(match.name)
        } else {
          unknown += 1
        }

        ctx.strokeStyle = known ? '#0f9f6f' : '#dc2626'
        ctx.lineWidth = 3
        ctx.strokeRect(box.x, box.y, box.width, box.height)
        ctx.fillStyle = known ? '#0f9f6f' : '#dc2626'
        ctx.fillRect(box.x, box.y + box.height - 22, box.width, 22)
        ctx.fillStyle = '#ffffff'
        ctx.font = '14px Poppins, sans-serif'
        ctx.fillText(known ? match.name : 'Unknown', box.x + 5, box.y + box.height - 6)
      }

      const presentUnique = [...new Set(recognized)]
      setSelectedGroupView(group)

      setProcessedPreview(canvas.toDataURL('image/jpeg', 0.9))
      setGroupStatus(
        `Processed group ${group}. Recognized: ${presentUnique.length ? presentUnique.join(', ') : 'none'} | Unknown: ${unknown}`,
      )

      URL.revokeObjectURL(imageURL)
    } catch (err) {
      setGroupStatus(`Group photo processing failed: ${err.message}`)
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <h1>SmartFace Attendance</h1>
        </div>
        <div className="topbar-actions">
          <div className={`model-pill ${modelsReady ? 'ok' : 'warn'}`}>{modelStatus}</div>
          <button type="button" className="topbar-btn" onClick={exportDataset}>
            Export Dataset
          </button>
          <button type="button" className="topbar-btn" onClick={() => datasetFileInputRef.current?.click()}>
            Import Dataset
          </button>
          <input
            ref={datasetFileInputRef}
            type="file"
            accept=".json,application/json"
            className="hidden-file"
            onChange={handleDatasetFileSelected}
          />
        </div>
      </header>

      {dataStatus && <p className="status-line" style={{ padding: '0 24px' }}>{dataStatus}</p>}

      <main className="layout">
        <section className="column-left">
          <article className="card card-register">
            <h2>Register Student</h2>
            <p className="card-note">Create robust recognition profiles with image upload or 8-shot capture.</p>
            {registerStatus && <p className="status-line">{registerStatus}</p>}

            <form onSubmit={handleRegisterSubmit} className="stack">
              <label>
                Student Name
                <input value={studentName} onChange={(e) => setStudentName(e.target.value)} placeholder="e.g. Student Name" required />
              </label>

              <label>
                Group
                <input value={studentGroup} onChange={(e) => setStudentGroup(e.target.value)} placeholder="e.g. B2" />
              </label>

              <label>
                Upload Photo
                <input
                  type="file"
                  accept="image/*"
                  onChange={(e) => setStudentPhoto(e.target.files?.[0] || null)}
                />
              </label>

              <div className="button-row">
                <button type="button" className="btn btn-secondary" onClick={captureEightSamples} disabled={isCapturingRegister}>
                  {isCapturingRegister ? 'Capturing...' : 'Capture 8 Photos'}
                </button>
                <button type="submit" className="btn btn-primary">
                  Register
                </button>
              </div>
            </form>
          </article>

          <article className="card card-group">
            <h2>Group Attendance</h2>
            <p className="card-note">Process a classroom photo and mark attendance for the selected group.</p>
            {groupStatus && <p className="status-line">{groupStatus}</p>}

            <form onSubmit={handleGroupPhotoSubmit} className="stack">
              <label>
                Group Name
                <input
                  value={groupScopeName}
                  onChange={(e) => setGroupScopeName(e.target.value)}
                  placeholder="Required for group sheet"
                />
              </label>

              <label>
                Classroom Photo
                <input type="file" accept="image/*" onChange={(e) => setGroupPhoto(e.target.files?.[0] || null)} required />
              </label>

              <div className="button-row">
                <button type="submit" className="btn btn-success">
                  Process Photo
                </button>
              </div>
            </form>

            {processedPreview && <img className="preview" src={processedPreview} alt="Processed classroom preview" />}
          </article>

          <article className="card card-dataset">
            <h2>Dataset Backup</h2>
            <p className="status-line">
              Export a full JSON backup or import and merge a previous SmartFace dataset, including students, face samples, and attendance history.
            </p>
            {datasetStatus && <p className="status-line">{datasetStatus}</p>}
            {datasetPreview && (
              <div className="dataset-preview" role="status">
                <strong>Import preview: {datasetPreview.fileName}</strong>
                <p>{datasetPreview.format}</p>
                <ul>
                  <li>{datasetPreview.studentCount} students</li>
                  <li>{datasetPreview.descriptorCount} face samples</li>
                  <li>{datasetPreview.attendanceCount} attendance records (estimated unique)</li>
                  <li>{datasetPreview.sessionCount} attendance sessions</li>
                </ul>
                <p className="card-note">Existing database records are kept. Matching students are merged, repeated face samples are ignored, and duplicate attendance for the same student/date is skipped.</p>
                <div className="button-row">
                  <button type="button" className="btn btn-primary" onClick={importDataset} disabled={isImportingDataset}>
                    {isImportingDataset ? 'Importing...' : 'Import & Merge'}
                  </button>
                  <button type="button" className="btn btn-secondary" onClick={cancelDatasetImport} disabled={isImportingDataset}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
            <div className="button-row">
              <button type="button" className="btn btn-accent" onClick={exportDataset}>
                Export Dataset
              </button>
              <button type="button" className="btn btn-primary" onClick={() => datasetFileInputRef.current?.click()}>
                Import Dataset
              </button>
            </div>
          </article>
        </section>

        <section className="column-right">
          <article className="card live-card card-live">
            <div className="live-head">
              <h2>Live Scanner</h2>
              <p>{cameraStatus}</p>
            </div>

            <div className="live-stage">
              {!isCameraOn && <div className="camera-placeholder">Camera offline. Start scanner to begin.</div>}
              <video ref={videoRef} autoPlay muted playsInline className={isCameraOn ? 'show' : 'hide'} onLoadedMetadata={syncOverlaySize} />
              <canvas ref={overlayRef} className={isCameraOn ? 'show overlay' : 'hide overlay'} />
            </div>

            <div className="button-row">
              <button
                className={`btn ${isCameraOn ? 'btn-danger' : 'btn-primary'}`}
                onClick={isCameraOn ? stopCamera : startLiveScanner}
              >
                {isCameraOn ? 'Stop Scanner' : 'Start Scanner'}
              </button>
            </div>
          </article>

          <article className="card card-table">
            <div className="section-head">
              <h2>Today's Attendance</h2>
              <div className="inline-controls">
                <input
                  value={filterGroup}
                  onChange={(e) => setFilterGroup(e.target.value)}
                  placeholder="Filter by group"
                />
              </div>
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Group</th>
                    <th>Time</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {!filteredAttendance.length && (
                    <tr>
                      <td colSpan="4" className="empty-row">
                        No records yet.
                      </td>
                    </tr>
                  )}
                  {filteredAttendance.map((row) => (
                    <tr key={row.id}>
                      <td>{row.name}</td>
                      <td>{row.group || '-'}</td>
                      <td>{row.time}</td>
                      <td>
                        <span className="chip">Present</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>

          <article className="card card-matrix">
            <div className="section-head">
              <h2>Group-wise Attendance Sheet</h2>
              <div className="inline-controls">
                <select value={selectedGroupView} onChange={(e) => setSelectedGroupView(e.target.value)}>
                  <option value="">Select Group</option>
                  {knownGroups.map((group) => (
                    <option key={group} value={group}>
                      {group}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn btn-accent"
                  onClick={() => exportGroupExcel(selectedGroupView)}
                  disabled={!selectedGroupView}
                >
                  Download Excel
                </button>
              </div>
            </div>

            {!selectedGroupView && <p className="status-line">Choose a group to view present/absent matrix.</p>}

            {selectedGroupView && (
              <div className="table-wrap matrix-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>names</th>
                      {(selectedGroupSheet?.timestamps || []).map((ts) => (
                        <th key={ts}>{formatTimestampLabel(ts)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {!(selectedGroupSheet?.rows || []).length && (
                      <tr>
                        <td colSpan={(selectedGroupSheet?.timestamps?.length || 0) + 1} className="empty-row">
                          No matrix data for this group yet.
                        </td>
                      </tr>
                    )}
                    {(selectedGroupSheet?.rows || []).map((row) => (
                      <tr key={row.Name}>
                        <td>{row.Name}</td>
                        {(selectedGroupSheet?.timestamps || []).map((ts) => (
                          <td key={`${row.Name}-${ts}`}>
                            <span className={row[ts] === 'p' ? 'chip ok' : 'chip bad'}>{row[ts] === 'p' ? 'p' : 'a'}</span>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </article>
        </section>
      </main>
    </div>
  )
}

export default App
