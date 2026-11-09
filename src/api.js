const API_BASE = 'http://127.0.0.1:8000'

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (res.status === 409) {
    const body = await res.json()
    const err = new Error(body.detail || 'Conflict')
    err.status = 409
    throw err
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed (${res.status})`)
  }
  return res
}

// Registers a student, or appends more descriptors if (name, group) already exists.
export async function apiRegisterStudent(name, group, descriptors) {
  const res = await request('/students', {
    method: 'POST',
    body: JSON.stringify({ name, group, descriptors }),
  })
  return res.json()
}

export async function apiListStudents() {
  const res = await request('/students')
  return res.json()
}

// Returns { alreadyMarked: true, message } instead of throwing on a 409,
// since "already marked today" is an expected outcome, not an error.
export async function apiMarkAttendance(studentId) {
  try {
    const res = await request('/attendance', {
      method: 'POST',
      body: JSON.stringify({ student_id: studentId }),
    })
    return { alreadyMarked: false, record: await res.json() }
  } catch (err) {
    if (err.status === 409) {
      return { alreadyMarked: true, message: err.message }
    }
    throw err
  }
}

export async function apiAttendanceToday(group = '') {
  const qs = group ? `?group=${encodeURIComponent(group)}` : ''
  const res = await request(`/attendance/today${qs}`)
  return res.json()
}

export async function apiAttendanceMatrix(group) {
  const res = await request(`/attendance/matrix?group=${encodeURIComponent(group)}`)
  return res.json()
}

export function apiExportGroupExcelUrl(group) {
  return `${API_BASE}/attendance/export?group=${encodeURIComponent(group)}`
}

export async function apiExportAll() {
  const res = await request('/export/all')
  return res.json()
}


// Merge a previously exported SmartFace dataset into the backend database.
export async function apiImportAll(dataset) {
  const res = await request('/import/all', {
    method: 'POST',
    body: JSON.stringify(dataset),
  })
  return res.json()
}
