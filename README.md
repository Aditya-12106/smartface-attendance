# SmartFace Attendance

A facial recognition-based attendance management system built using React and FastAPI. The application enables student registration, real-time face recognition, group photo processing, attendance tracking, and automated report generation.

## Features

- **Student Registration:** Register students using uploaded photographs or an 8-photo webcam capture workflow.
- **Face Recognition:** Detect and recognize registered students through a live webcam scanner.
- **Group Attendance:** Process classroom photographs to identify multiple students and mark their attendance.
- **Attendance Tracking:** View daily attendance records with filtering by student group.
- **Attendance Matrix:** Generate group-wise attendance sheets showing Present/Absent status across dates.
- **Excel Export:** Download group-wise attendance reports as Excel files.
- **Dataset Export:** Export a complete JSON backup containing student records, face descriptors, and attendance history.
- **Dataset Import:** Import and merge previously exported datasets, with duplicate detection to prevent redundant student records, face samples, and attendance entries.

## Architecture

The application follows a client-server architecture.

```text
                Browser
                   |
          React Frontend (Vite)
                   |
          face-api.js
     Face Detection & Recognition
                   |
         Face Descriptors
                   |
                   v
             FastAPI Backend
                   |
             SQLAlchemy ORM
                   |
                   v
              SQLite Database
                   |
          Attendance & Student Data
```

Face detection and recognition run in the browser using `face-api.js` and pretrained models. The frontend extracts numerical face descriptors and communicates with the backend through REST APIs. The backend manages student records, face descriptors, attendance data, and report generation.

## Tech Stack

**Frontend**
- React 19
- Vite 8
- face-api.js
- JavaScript
- HTML5 / CSS3

**Backend**
- Python
- FastAPI
- SQLAlchemy
- SQLite
- REST APIs

**Additional Tools**
- pytest
- Excel report generation
- JSON-based dataset backup and restoration

## Project Structure

```text
SmartFace-Attendance/
│
├── api/
│   ├── main.py
│   ├── requirements.txt
│   ├── attendance.db
│   └── ...
│
├── backend/
│   └── ...
│
├── frontend/
│   └── ...
│
├── src/
│   ├── App.jsx
│   ├── api.js
│   └── ...
│
├── index.html
├── package.json
├── package-lock.json
├── vite.config.js
├── .gitignore
└── README.md
```

## Getting Started

### Prerequisites

- Python 3.10 or later
- Node.js and npm
- A webcam for live face capture and recognition
- Internet access for loading the face recognition library and pretrained models

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/smartface-attendance.git
cd smartface-attendance
```

### 2. Start the Backend

```bash
cd api

python -m venv venv
```

Activate the virtual environment:

**Windows:**
```bash
venv\Scripts\activate
```

**Linux / macOS:**
```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the FastAPI server:

```bash
python -m uvicorn main:app --reload --port 8000
```

The backend will be available at:

`http://127.0.0.1:8000`

Interactive API documentation:

`http://127.0.0.1:8000/docs`

### 3. Start the Frontend

Open a separate terminal in the project root:

```bash
npm install
npm run dev
```

Open the local development URL provided by Vite, usually:

`http://localhost:5173`

### 4. Run Backend Tests

From the `api/` directory:

```bash
pytest -v
```

## Production Build

To generate the production frontend build:

```bash
npm run build
```

The generated files are placed in the `dist/` directory.

The frontend requires a reachable FastAPI backend. Before deploying, configure the API base URL in `src/api.js` to point to the deployed backend rather than `127.0.0.1`.

The frontend and backend must be deployed separately when using static hosting platforms such as GitHub Pages.

## Dataset Management

The application provides JSON-based dataset backup and restoration.

**Export Dataset**
- Exports student information.
- Includes stored face descriptors.
- Includes attendance history and group attendance data.

**Import Dataset**
- Supports previously exported SmartFace datasets.
- Supports the legacy browser-based dataset format.
- Merges existing and new student records.
- Avoids adding duplicate face samples and attendance records.
- Preserves historical attendance information.

## Database

Student information, face descriptors, and attendance records are managed through SQLite using SQLAlchemy.

The active database is:

```text
api/attendance.db
```

The application uses the database for persistent storage of student registrations and attendance information.

## Notes

- Face detection and recognition run client-side in the browser.
- The application requires webcam permissions for live capture and scanning.
- AI model loading depends on access to the configured public CDN resources.
- The backend must be running for registration, attendance operations, dataset import, and database-backed exports.
- The default local API configuration must be changed before public deployment.
- Real student photographs and biometric descriptors should only be collected and distributed with appropriate consent and safeguards.