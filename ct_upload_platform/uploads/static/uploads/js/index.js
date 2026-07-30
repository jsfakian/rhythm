        // Configuration
        const API_BASE_URL = '/api/v1';
        const MAX_UPLOAD_SIZE_MB = Number(document.body.dataset.maxUploadSizeMb);
        const MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024;
        const POLL_INTERVAL_MS = 3000;
        const MAX_RETRIES = 30; // 90 seconds max
        const STATUS_TERMINAL = ['COMPLETE', 'FAILED', 'PARTIAL'];

        // DOM Elements
        const form = document.getElementById('uploadForm');
        const apiTokenInput = document.getElementById('apiToken');
        const uploaderIdInput = document.getElementById('uploaderId');
        const tarFileInput = document.getElementById('tarFile');
        const uploadBtn = document.getElementById('uploadBtn');
        const alertDiv = document.getElementById('alert');
        const progressContainer = document.getElementById('progressContainer');
        const progressFill = progressContainer.querySelector('.progress-fill');
        const progressText = document.getElementById('progressText');
        const statusPanel = document.getElementById('statusPanel');
        const statusValue = document.getElementById('statusValue');
        const jobIdSpan = document.getElementById('jobId');
        const submittedAtSpan = document.getElementById('submittedAt');
        const imageCountSpan = document.getElementById('imageCount');
        const completedAtSpan = document.getElementById('completedAt');
        const errorsSection = document.getElementById('errorsSection');
        const errorsToggle = document.getElementById('errorsToggle');
        const errorsTable = document.getElementById('errorsTable');
        const errorsBody = document.getElementById('errorsBody');
        const errorsCount = document.getElementById('errorsCount');

        // State
        let currentJobId = null;
        let pollCount = 0;
        let pollIntervalId = null;

        // Utility Functions
        function showAlert(message, type = 'error') {
            alertDiv.textContent = message;
            alertDiv.className = `alert show alert-${type}`;
            window.scrollTo(0, 0);
        }

        function hideAlert() {
            alertDiv.classList.remove('show');
        }

        function validateFile() {
            const file = tarFileInput.files[0];
            if (!file) {
                showAlert('Please select a file');
                return false;
            }

            // Check file size
            if (file.size > MAX_UPLOAD_SIZE_BYTES) {
                const sizeMB = (file.size / (1024 * 1024)).toFixed(2);
                showAlert(
                    `File size (${sizeMB}MB) exceeds maximum (${MAX_UPLOAD_SIZE_MB}MB)`,
                    'error'
                );
                return false;
            }

            // Check file extension
            const name = file.name.toLowerCase();
            if (!name.endsWith('.tar') && !name.endsWith('.tar.gz')) {
                showAlert('File must be a .tar or .tar.gz archive', 'error');
                return false;
            }

            return true;
        }

        function getAuthHeaders() {
            const token = apiTokenInput.value.trim();
            if (!token) {
                showAlert('API token is required', 'error');
                return null;
            }
            
            // Store in sessionStorage
            try {
                sessionStorage.setItem('apiToken', token);
            } catch (e) {
                console.error('Failed to store token:', e);
            }

            return {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            };
        }

        function formatDate(dateString) {
            if (!dateString) return '-';
            try {
                const date = new Date(dateString);
                return date.toLocaleString();
            } catch {
                return dateString;
            }
        }

        function formatStatusBadge(status) {
            const badgeClass = `status-${status.toLowerCase()}`;
            return status;
        }

        function displayErrors(errorReport) {
            if (!errorReport || errorReport.length === 0) {
                errorsSection.classList.add('hidden');
                return;
            }

            errorsSection.classList.remove('hidden');
            errorsCount.textContent = errorReport.length;
            errorsBody.innerHTML = '';

            errorReport.forEach((error) => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${escapeHtml(error.field || '-')}</td>
                    <td>${escapeHtml(error.code || '-')}</td>
                    <td class="error-message">${escapeHtml(error.message || 'Unknown error')}</td>
                `;
                errorsBody.appendChild(row);
            });
        }

        function escapeHtml(text) {
            const map = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            };
            return text.replace(/[&<>"']/g, m => map[m]);
        }

        function updateStatusPanel(job) {
            jobIdSpan.textContent = job.id;
            submittedAtSpan.textContent = formatDate(job.submitted_at);
            completedAtSpan.textContent = formatDate(job.completed_at) || '-';
            imageCountSpan.textContent = job.image_count || 0;

            const status = job.status.toUpperCase();
            statusValue.textContent = status;
            statusValue.className = `status-value status-${status.toLowerCase()}`;

            displayErrors(job.error_report);
        }

        function showProgress(uploadedBytes, totalBytes) {
            progressContainer.classList.add('show');
            const percentage = Math.round((uploadedBytes / totalBytes) * 100);
            progressFill.style.width = percentage + '%';
            progressText.textContent = `Uploading... ${percentage}%`;
        }

        function hideProgress() {
            progressContainer.classList.remove('show');
            progressFill.style.width = '0%';
        }

        function stopPolling() {
            if (pollIntervalId) {
                clearInterval(pollIntervalId);
                pollIntervalId = null;
            }
            pollCount = 0;
        }

        function pollJobStatus(jobId) {
            if (pollCount >= MAX_RETRIES) {
                showAlert('Poll timeout - job may still be processing', 'error');
                stopPolling();
                return;
            }

            const token = sessionStorage.getItem('apiToken');
            if (!token) {
                showAlert('API token lost from session', 'error');
                stopPolling();
                return;
            }

            fetch(`${API_BASE_URL}/uploads/${jobId}/`, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'application/json'
                }
            })
                .then(response => {
                    if (response.status === 401) {
                        throw new Error('Invalid API token (401 Unauthorized)');
                    }
                    if (!response.ok) {
                        throw new Error(`HTTP ${response.status}`);
                    }
                    return response.json();
                })
                .then(job => {
                    updateStatusPanel(job);
                    
                    if (STATUS_TERMINAL.includes(job.status)) {
                        stopPolling();
                        if (job.status === 'COMPLETE') {
                            showAlert('Upload completed successfully!', 'success');
                        } else if (job.status === 'PARTIAL') {
                            showAlert('Upload completed with errors (see details below)', 'info');
                        } else {
                            showAlert('Upload failed', 'error');
                        }
                    }
                })
                .catch(error => {
                    console.error('Poll error:', error);
                    showAlert(`Poll error: ${error.message}`, 'error');
                    stopPolling();
                });

            pollCount++;
        }

        function startPolling(jobId) {
            currentJobId = jobId;
            pollCount = 0;
            statusPanel.classList.add('show');
            progressText.textContent = 'Processing... (polling for status)';

            // First poll immediately
            pollJobStatus(jobId);

            // Then poll at intervals
            pollIntervalId = setInterval(() => {
                pollJobStatus(jobId);
            }, POLL_INTERVAL_MS);
        }

        // Form Submission
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            hideAlert();

            // Validate
            if (!apiTokenInput.value.trim()) {
                showAlert('API token is required', 'error');
                return;
            }

            if (!validateFile()) {
                return;
            }

            // Disable form during upload
            uploadBtn.disabled = true;
            tarFileInput.disabled = true;

            try {
                const formData = new FormData();
                formData.append('tar_file', tarFileInput.files[0]);
                if (uploaderIdInput.value.trim()) {
                    formData.append('uploader_id', uploaderIdInput.value.trim());
                }

                // Use XMLHttpRequest for upload progress
                const xhr = new XMLHttpRequest();

                // Progress event
                xhr.upload.addEventListener('progress', (e) => {
                    if (e.lengthComputable) {
                        showProgress(e.loaded, e.total);
                    }
                });

                // Load event (the request is done)
                xhr.addEventListener('load', () => {
                    if (xhr.status === 202) {
                        try {
                            const response = JSON.parse(xhr.responseText);
                            startPolling(response.job_id);
                            hideProgress();
                            showAlert('Upload accepted! Processing...', 'success');
                        } catch (e) {
                            showAlert('Invalid response from server', 'error');
                            uploadBtn.disabled = false;
                            tarFileInput.disabled = false;
                        }
                    } else if (xhr.status === 401) {
                        showAlert('Invalid API token (401 Unauthorized)', 'error');
                        uploadBtn.disabled = false;
                        tarFileInput.disabled = false;
                    } else if (xhr.status === 413) {
                        showAlert('File is too large', 'error');
                        uploadBtn.disabled = false;
                        tarFileInput.disabled = false;
                    } else if (xhr.status === 400) {
                        try {
                            const error = JSON.parse(xhr.responseText);
                            showAlert(`Bad request: ${error.error || 'Unknown'}`, 'error');
                        } catch {
                            showAlert('Bad request - invalid file format?', 'error');
                        }
                        uploadBtn.disabled = false;
                        tarFileInput.disabled = false;
                    } else if (xhr.status >= 500) {
                        showAlert(`Server error (${xhr.status})`, 'error');
                        uploadBtn.disabled = false;
                        tarFileInput.disabled = false;
                    } else {
                        showAlert(`Upload failed (HTTP ${xhr.status})`, 'error');
                        uploadBtn.disabled = false;
                        tarFileInput.disabled = false;
                    }
                });

                // Error event
                xhr.addEventListener('error', () => {
                    showAlert('Network error - could not connect to server', 'error');
                    uploadBtn.disabled = false;
                    tarFileInput.disabled = false;
                });

                // Abort event
                xhr.addEventListener('abort', () => {
                    showAlert('Upload cancelled', 'error');
                    uploadBtn.disabled = false;
                    tarFileInput.disabled = false;
                });

                // Send request
                xhr.open('POST', `${API_BASE_URL}/uploads/`);
                xhr.setRequestHeader('Authorization', `Bearer ${apiTokenInput.value.trim()}`);
                xhr.send(formData);

            } catch (error) {
                showAlert(`Error: ${error.message}`, 'error');
                uploadBtn.disabled = false;
                tarFileInput.disabled = false;
            }
        });

        // Errors toggle
        errorsToggle.addEventListener('click', () => {
            errorsToggle.classList.toggle('expanded');
            errorsTable.classList.toggle('show');
        });

        // Restore token from sessionStorage on page load
        window.addEventListener('load', () => {
            try {
                const savedToken = sessionStorage.getItem('apiToken');
                if (savedToken) {
                    apiTokenInput.value = savedToken;
                }
            } catch (e) {
                console.error('Failed to restore token:', e);
            }
        });

        // Clear polling on page unload
        window.addEventListener('beforeunload', () => {
            stopPolling();
        });
