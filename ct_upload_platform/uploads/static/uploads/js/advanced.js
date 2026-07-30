        // ============== Core Configuration ==============
        const API_BASE_URL = '/api/v1';
        const STORAGE_KEY_TOKEN = 'ct_api_token';
        const POLL_INTERVAL = 3000;
        const MAX_RETRIES = 30;

        // ============== State Management ==============
        let currentToken = null;
        let currentPage = 'home';
        let pollIntervals = new Map();
        let chunkedUploadState = {
            sessionId: null,
            totalChunks: 0,
            uploadedChunks: 0,
            fileSize: 0,
            chunkSize: 0,
            aborted: false,
            isPaused: false
        };

        // ============== Utility Functions ==============
        function showAlert(message, type = 'error') {
            const alert = document.getElementById('alert');
            alert.textContent = message;
            alert.className = `alert show alert-${type}`;
            window.scrollTo(0, 0);
        }

        function hideAlert() {
            document.getElementById('alert').classList.remove('show');
        }

        function getAuthHeaders() {
            if (!currentToken) {
                showAlert('API token not configured. Go to Settings to add your token.', 'error');
                changePage('settings');
                return null;
            }
            return {
                'Authorization': `Bearer ${currentToken}`,
                'Content-Type': 'application/json'
            };
        }

        async function apiCall(endpoint, options = {}) {
            const headers = getAuthHeaders();
            if (!headers) return null;

            const response = await fetch(`${API_BASE_URL}${endpoint}`, {
                headers: { ...headers, ...options.headers },
                ...options
            });

            if (!response.ok) {
                if (response.status === 401) {
                    showAlert('Unauthorized. Please check your API token.', 'error');
                    changePage('settings');
                } else {
                    let errorMsg = `HTTP ${response.status}`;
                    try {
                        const errorData = await response.json();
                        errorMsg = errorData.error || errorData.detail || errorMsg;
                    } catch (e) {}
                    showAlert(`Error: ${errorMsg}`, 'error');
                }
                return null;
            }

            return await response.json();
        }

        function formatDate(dateString) {
            if (!dateString) return '-';
            return new Date(dateString).toLocaleString();
        }

        // ============== Navigation ==============
        function changePage(pageName) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('[data-page]').forEach(n => n.classList.remove('active'));

            document.getElementById(pageName).classList.add('active');
            document.querySelector(`[data-page="${pageName}"]`).classList.add('active');
            currentPage = pageName;

            // Load page-specific data
            if (pageName === 'uploads') loadUploads();
            if (pageName === 'studies') loadStudies();
        }

        document.querySelectorAll('[data-page]').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                changePage(item.dataset.page);
            });
        });

        // ============== Settings Tab ==============
        function loadTokenFromStorage() {
            const stored = sessionStorage.getItem(STORAGE_KEY_TOKEN);
            if (stored) {
                currentToken = stored;
                document.getElementById('apiToken').value = stored;
            }
        }

        document.getElementById('saveTokenBtn').addEventListener('click', () => {
            const token = document.getElementById('apiToken').value.trim();
            if (!token) {
                showAlert('Please enter an API token', 'error');
                return;
            }
            currentToken = token;
            sessionStorage.setItem(STORAGE_KEY_TOKEN, token);
            showAlert('API token saved!', 'success');
        });

        document.getElementById('clearTokenBtn').addEventListener('click', () => {
            currentToken = null;
            document.getElementById('apiToken').value = '';
            sessionStorage.removeItem(STORAGE_KEY_TOKEN);
            showAlert('API token cleared', 'info');
        });

        document.getElementById('toggleTokenVisibility').addEventListener('click', (e) => {
            const input = document.getElementById('apiToken');
            const isPassword = input.type === 'password';
            input.type = isPassword ? 'text' : 'password';
            e.target.textContent = isPassword ? 'Hide' : 'Show';
        });

        // ============== Single File Upload ==============
        const singleUploadToggle = document.getElementById('toggleSingleUpload');
        const chunkedUploadToggle = document.getElementById('toggleChunkedUpload');
        const singleUploadSection = document.getElementById('singleUploadSection');
        const chunkedUploadSection = document.getElementById('chunkedUploadSection');

        singleUploadToggle.addEventListener('click', () => {
            singleUploadSection.style.display = 'block';
            chunkedUploadSection.style.display = 'none';
            singleUploadToggle.classList.add('btn-active');
            chunkedUploadToggle.classList.remove('btn-active');
        });

        chunkedUploadToggle.addEventListener('click', () => {
            singleUploadSection.style.display = 'none';
            chunkedUploadSection.style.display = 'block';
            singleUploadToggle.classList.remove('btn-active');
            chunkedUploadToggle.classList.add('btn-active');
        });

        document.getElementById('singleUploadForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const file = document.getElementById('singleFile').files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('tar_file', file);
            const uploaderId = document.getElementById('singleUploaderId').value;
            if (uploaderId) formData.append('uploader_id', uploaderId);

            const headers = getAuthHeaders();
            if (!headers) return;

            const progressContainer = document.querySelector('#singleUploadSection .progress-container');
            progressContainer.style.display = 'block';

            const xhr = new XMLHttpRequest();
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable) {
                    const percent = (e.loaded / e.total) * 100;
                    document.querySelector('#singleUploadSection .progress-fill').style.width = percent + '%';
                    document.getElementById('singleUploadStatus').textContent = `Uploading... ${Math.round(percent)}%`;
                }
            });

            xhr.addEventListener('load', () => {
                progressContainer.style.display = 'none';
                if (xhr.status === 202) {
                    const response = JSON.parse(xhr.responseText);
                    showAlert(`Upload submitted! Job ID: ${response.job_id}`, 'success');
                    document.getElementById('singleUploadForm').reset();
                    startPollingSingleUpload(response.job_id);
                } else {
                    showAlert(`Upload failed: ${xhr.statusText}`, 'error');
                }
            });

            xhr.addEventListener('error', () => {
                progressContainer.style.display = 'none';
                showAlert('Network error during upload', 'error');
            });

            xhr.open('POST', `${API_BASE_URL}/uploads/`);
            xhr.setRequestHeader('Authorization', headers['Authorization']);
            xhr.send(formData);
        });

        function startPollingSingleUpload(jobId) {
            showAlert(`Polling job status... (Job: ${jobId})`, 'info');
            let retries = 0;

            const poll = async () => {
                if (retries++ > MAX_RETRIES) {
                    showAlert('Poll timeout', 'error');
                    return;
                }

                const job = await apiCall(`/uploads/${jobId}/`);
                if (!job) return;

                if (['COMPLETE', 'FAILED', 'PARTIAL'].includes(job.status)) {
                    clearInterval(pollIntervals.get(jobId));
                    pollIntervals.delete(jobId);
                    showAlert(`Job ${job.status.toLowerCase()}!`, job.status === 'COMPLETE' ? 'success' : 'info');
                }
            };

            poll();
            pollIntervals.set(jobId, setInterval(poll, POLL_INTERVAL));
        }

        // ============== Chunked Upload ==============
        document.getElementById('chunkedUploadForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const file = document.getElementById('chunkedFile').files[0];
            if (!file) return;

            const chunkSizeMB = parseInt(document.getElementById('chunkSize').value);
            const chunkSizeBytes = chunkSizeMB * 1024 * 1024;

            // Initialize chunked upload
            const headers = getAuthHeaders();
            if (!headers) return;

            const initResponse = await apiCall('/uploads/chunked/init/', {
                method: 'POST',
                headers,
                body: JSON.stringify({
                    filename: file.name,
                    file_size: file.size,
                    chunk_size: chunkSizeBytes
                })
            });

            if (!initResponse) return;

            chunkedUploadState = {
                sessionId: initResponse.session_id,
                totalChunks: initResponse.total_chunks,
                uploadedChunks: 0,
                fileSize: file.size,
                chunkSize: chunkSizeBytes,
                aborted: false,
                isPaused: false
            };

            document.getElementById('chunkedUploadWidget').style.display = 'block';
            document.getElementById('chunkedFileName').textContent = file.name;
            document.getElementById('totalChunks').textContent = chunkedUploadState.totalChunks;
            document.getElementById('cancelChunkedBtn').style.display = 'inline-block';

            startChunkedUpload(file);
        });

        async function startChunkedUpload(file) {
            const chunkSizeBytes = chunkedUploadState.chunkSize;
            const totalChunks = chunkedUploadState.totalChunks;

            for (let i = 0; i < totalChunks; i++) {
                if (chunkedUploadState.aborted) break;
                if (chunkedUploadState.isPaused) {
                    await new Promise(resolve => {
                        const checkPaused = setInterval(() => {
                            if (!chunkedUploadState.isPaused || chunkedUploadState.aborted) {
                                clearInterval(checkPaused);
                                resolve();
                            }
                        }, 100);
                    });
                }

                const start = i * chunkSizeBytes;
                const end = Math.min(start + chunkSizeBytes, file.size);
                const chunkData = file.slice(start, end);

                const crypto = window.crypto || window.msCrypto;
                const buffer = await chunkData.arrayBuffer();
                const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
                const hashArray = Array.from(new Uint8Array(hashBuffer));
                const hashHex = hashArray.map(b => b.toString(16).padStart(2, '0')).join('');

                const formData = new FormData();
                formData.append('chunk_data', chunkData);

                const headers = getAuthHeaders();
                if (!headers) return;

                const response = await fetch(
                    `${API_BASE_URL}/uploads/chunked/${chunkedUploadState.sessionId}/chunk/?chunk_number=${i}&chunk_hash=${hashHex}`,
                    {
                        method: 'POST',
                        headers: { 'Authorization': headers['Authorization'] },
                        body: formData
                    }
                );

                if (response.ok) {
                    const result = await response.json();
                    chunkedUploadState.uploadedChunks = result.uploaded_chunks;
                    document.getElementById('uploadedChunks').textContent = result.uploaded_chunks;
                    document.getElementById('verifiedChunks').textContent = result.verified_chunks || 0;
                    document.getElementById('corruptedChunks').textContent = result.corrupted_chunks || 0;

                    const percent = (chunkedUploadState.uploadedChunks / totalChunks) * 100;
                    document.getElementById('chunkedProgressFill').style.width = percent + '%';
                    document.getElementById('chunkedUploadStatus').textContent = 
                        `Uploaded ${chunkedUploadState.uploadedChunks}/${totalChunks} chunks`;

                    if (result.corrupted_chunks > 0) {
                        // Show failed chunks for retry
                        document.getElementById('failedChunksList').style.display = 'block';
                    }
                } else {
                    showAlert(`Chunk ${i} upload failed`, 'error');
                }
            }

            if (!chunkedUploadState.aborted) {
                completeChunkedUpload();
            }
        }

        async function completeChunkedUpload() {
            const crypto = window.crypto || window.msCrypto;
            
            const headers = getAuthHeaders();
            if (!headers) return;

            const fileHash = 'mock_hash_' + Date.now(); // In real scenario, compute actual file hash

            const response = await apiCall(`/uploads/chunked/${chunkedUploadState.sessionId}/complete/`, {
                method: 'POST',
                headers,
                body: JSON.stringify({ file_hash: fileHash })
            });

            if (response) {
                showAlert(`Chunked upload complete! Job ID: ${response.job_id}`, 'success');
                chunkedUploadState = {};
                document.getElementById('chunkedUploadWidget').style.display = 'none';
                document.getElementById('chunkedUploadForm').reset();
            }
        }

        document.getElementById('cancelChunkedBtn').addEventListener('click', async () => {
            chunkedUploadState.aborted = true;

            const headers = getAuthHeaders();
            if (!headers) return;

            await fetch(
                `${API_BASE_URL}/uploads/chunked/${chunkedUploadState.sessionId}/`,
                {
                    method: 'DELETE',
                    headers
                }
            );

            showAlert('Chunked upload cancelled', 'info');
            document.getElementById('chunkedUploadWidget').style.display = 'none';
            chunkedUploadState = {};
        });

        // ============== Manifest Validation ==============
        document.getElementById('manifestForm').addEventListener('submit', async (e) => {
            e.preventDefault();

            let manifestText = document.getElementById('manifestJson').value.trim();

            if (!manifestText && document.getElementById('manifestFile').files.length > 0) {
                const file = document.getElementById('manifestFile').files[0];
                manifestText = await file.text();
            }

            if (!manifestText) {
                showAlert('Please enter or upload manifest JSON', 'error');
                return;
            }

            let manifest;
            try {
                manifest = JSON.parse(manifestText);
            } catch (e) {
                showAlert(`Invalid JSON: ${e.message}`, 'error');
                return;
            }

            const headers = getAuthHeaders();
            if (!headers) return;

            const response = await apiCall('/uploads/validate-manifest/', {
                method: 'POST',
                headers,
                body: JSON.stringify({ manifest })
            });

            if (!response) return;

            document.getElementById('manifestResults').style.display = 'block';

            if (response.valid) {
                document.getElementById('manifestValid').style.display = 'block';
                document.getElementById('manifestInvalid').style.display = 'none';
            } else {
                document.getElementById('manifestValid').style.display = 'none';
                document.getElementById('manifestInvalid').style.display = 'block';

                const tbody = document.getElementById('manifestErrorsBody');
                tbody.innerHTML = '';
                response.errors.forEach(error => {
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td>${error.field || '-'}</td>
                        <td>${error.code || '-'}</td>
                        <td>${error.message || 'Unknown error'}</td>
                    `;
                    tbody.appendChild(row);
                });
            }
        });

        // ============== My Uploads Tab ==============
        async function loadUploads() {
            const response = await apiCall('/uploads/');
            if (!response) return;

            const tbody = document.getElementById('uploadsBody');
            const empty = document.getElementById('uploadsEmpty');
            const uploads = response.results || response;

            if (!uploads || uploads.length === 0) {
                tbody.innerHTML = '';
                empty.style.display = 'block';
                return;
            }

            empty.style.display = 'none';
            tbody.innerHTML = uploads.map(job => `
                <tr>
                    <td>${job.id}</td>
                    <td><span class="status-badge status-${job.status.toLowerCase()}">${job.status}</span></td>
                    <td>${formatDate(job.submitted_at)}</td>
                    <td>${job.image_count || 0}</td>
                    <td>${formatDate(job.completed_at)}</td>
                    <td>
                        <button class="btn-secondary" onclick="viewUploadDetails('${job.id}')">View</button>
                        <button class="btn-danger" onclick="deleteUpload('${job.id}')">Delete</button>
                    </td>
                </tr>
            `).join('');
        }

        async function deleteUpload(jobId) {
            if (!confirm('Are you sure you want to delete this upload?')) return;

            const headers = getAuthHeaders();
            if (!headers) return;

            await fetch(`${API_BASE_URL}/uploads/${jobId}/`, {
                method: 'DELETE',
                headers
            });

            showAlert('Upload deleted', 'success');
            loadUploads();
        }

        async function viewUploadDetails(jobId) {
            const response = await apiCall(`/uploads/${jobId}/`);
            if (!response) return;
            
            // Display details in an overlay/modal
            const details = `
                <div style="background: white; padding: 20px; border-radius: 6px; margin-top: 20px;">
                    <h2>Upload Details</h2>
                    <table style="width: 100%; margin-top: 15px;">
                        <tr><td style="font-weight: 600;">Job ID:</td><td>${response.id}</td></tr>
                        <tr><td style="font-weight: 600;">Filename:</td><td>${response.filename || '-'}</td></tr>
                        <tr><td style="font-weight: 600;">Status:</td><td><span class="status-badge status-${response.status.toLowerCase()}">${response.status}</span></td></tr>
                        <tr><td style="font-weight: 600;">Images:</td><td>${response.image_count || 0}</td></tr>
                        <tr><td style="font-weight: 600;">Submitted:</td><td>${formatDate(response.submitted_at)}</td></tr>
                        <tr><td style="font-weight: 600;">Completed:</td><td>${formatDate(response.completed_at)}</td></tr>
                        <tr><td style="font-weight: 600;">Uploader:</td><td>${response.uploader_id || '-'}</td></tr>
                        <tr><td style="font-weight: 600;">Size:</td><td>${Math.round((response.file_size || 0) / 1024 / 1024)} MB</td></tr>
                    </table>
                    <button class="btn-secondary" onclick="location.reload()" style="margin-top: 20px;">Close</button>
                </div>
            `;
            
            document.getElementById('uploadsBody').parentElement.insertAdjacentHTML('afterend', details);
        }

        document.getElementById('refreshUploadsBtn').addEventListener('click', loadUploads);

        // ============== Studies Tab ==============
        async function loadStudies() {
            const response = await apiCall('/studies/');
            if (!response) return;

            const tbody = document.getElementById('studiesBody');
            const empty = document.getElementById('studiesEmpty');
            const studies = response.results || response;

            if (!studies || studies.length === 0) {
                tbody.innerHTML = '';
                empty.style.display = 'block';
                return;
            }

            empty.style.display = 'none';
            tbody.innerHTML = studies.map(study => `
                <tr>
                    <td>${study.pseudo_study_uid}</td>
                    <td><code>${study.orthanc_study_id}</code></td>
                    <td>${study.series_count || '-'}</td>
                    <td>${study.instances_count || '-'}</td>
                    <td>${formatDate(study.last_modified)}</td>
                    <td>
                        <button class="btn-secondary" onclick="viewStudyDetails('${study.pseudo_study_uid}')">View</button>
                    </td>
                </tr>
            `).join('');
        }

        function viewStudyDetails(studyUid) {
            // Fetch and display study details
            loadStudyDetail(studyUid);
        }

        async function loadStudyDetail(studyUid) {
            const response = await apiCall(`/studies/${studyUid}/`);
            if (!response) return;
            
            const details = `
                <div style="background: white; padding: 20px; border-radius: 6px; margin-top: 20px;">
                    <h2>Study Details</h2>
                    <table style="width: 100%; margin-top: 15px;">
                        <tr><td style="font-weight: 600;">Pseudo Study UID:</td><td>${response.pseudo_study_uid}</td></tr>
                        <tr><td style="font-weight: 600;">Orthanc Study ID:</td><td><code>${response.orthanc_study_id}</code></td></tr>
                        <tr><td style="font-weight: 600;">Series Count:</td><td>${response.series_count || '-'}</td></tr>
                        <tr><td style="font-weight: 600;">Instances Count:</td><td>${response.instances_count || '-'}</td></tr>
                        <tr><td style="font-weight: 600;">Last Modified:</td><td>${formatDate(response.last_modified)}</td></tr>
                        <tr><td style="font-weight: 600;">Patient ID:</td><td>${response.patient_pseudo_id || '-'}</td></tr>
                        <tr><td style="font-weight: 600;">Study Description:</td><td>${response.study_description || '-'}</td></tr>
                    </table>
                    <button class="btn-secondary" onclick="location.reload()" style="margin-top: 20px;">Close</button>
                </div>
            `;
            
            document.getElementById('studiesBody').parentElement.insertAdjacentHTML('afterend', details);
        }

        document.getElementById('refreshStudiesBtn').addEventListener('click', loadStudies);

        // ============== Initialization ==============
        loadTokenFromStorage();

        // ============== Logout ==============
        // Handled by the server-side /logout/ endpoint via the sidebar link.
