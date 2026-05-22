import { test as base, expect } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';
import * as zlib from 'zlib';
import { createWriteStream, createReadStream } from 'fs';
import { pipeline } from 'stream/promises';

/**
 * Test fixtures and helpers for CT Upload Platform E2E tests
 */

// Extend test with custom fixtures
export const test = base.extend({
  testDataDir: async ({}, use) => {
    const tempDir = path.join(__dirname, '../../temp_test_data');
    if (!fs.existsSync(tempDir)) {
      fs.mkdirSync(tempDir, { recursive: true });
    }
    await use(tempDir);
    // Cleanup after tests
    // fs.rmSync(tempDir, { recursive: true });
  },
});

export { expect };

/**
 * Create a minimal TAR archive for testing
 */
export async function createTestTarArchive(tempDir: string, options: {
  fileName?: string;
  compressed?: boolean;
  includeFiles?: number;
} = {}): Promise<string> {
  const {
    fileName = 'test-upload.tar',
    compressed = false,
    includeFiles = 2,
  } = options;

  const filePath = path.join(tempDir, fileName);
  const tarStream = createWriteStream(filePath);
  
  // Create a simple TAR archive using the tar command
  const { execSync } = require('child_process');
  
  // Create temp directory with test files
  const sourcesDir = path.join(tempDir, 'sources');
  if (!fs.existsSync(sourcesDir)) {
    fs.mkdirSync(sourcesDir, { recursive: true });
  }

  // Create test files
  for (let i = 0; i < includeFiles; i++) {
    const testFile = path.join(sourcesDir, `dicom_file_${i}.dcm`);
    fs.writeFileSync(testFile, Buffer.from(`DICM_HEADER_${i}${'x'.repeat(1000)}`));
  }

  // Create tar archive
  try {
    execSync(`cd ${tempDir} && tar -cf ${fileName} sources/`);
    
    // Compress if needed
    if (compressed && fileName.endsWith('.tar')) {
      const gzipFileName = fileName.replace('.tar', '.tar.gz');
      const gzipPath = path.join(tempDir, gzipFileName);
      await pipeline(
        createReadStream(filePath),
        zlib.createGzip(),
        createWriteStream(gzipPath)
      );
      fs.unlinkSync(filePath);
      return gzipPath;
    }
    
    return filePath;
  } catch (error) {
    console.error('Failed to create tar archive:', error);
    throw error;
  }
}

/**
 * Create a TAR archive that exceeds the max upload size
 */
export async function createOversizedTarArchive(tempDir: string, maxSizeMB: number): Promise<string> {
  const filePath = path.join(tempDir, 'oversized.tar');
  
  const { execSync } = require('child_process');
  
  // Create a large file that exceeds the limit (add 1 MB extra to be sure)
  const fileSizeBytes = (maxSizeMB + 1) * 1024 * 1024;
  const sourcesDir = path.join(tempDir, 'large_sources');
  
  if (!fs.existsSync(sourcesDir)) {
    fs.mkdirSync(sourcesDir, { recursive: true });
  }

  // Create a file that's too large
  const largeFile = path.join(sourcesDir, 'large_file.bin');
  fs.writeFileSync(largeFile, Buffer.alloc(fileSizeBytes));

  try {
    execSync(`cd ${tempDir} && tar -cf oversized.tar large_sources/`);
    return filePath;
  } catch (error) {
    console.error('Failed to create oversized tar:', error);
    throw error;
  }
}

/**
 * Test credentials
 */
export const TEST_CREDENTIALS = {
  validToken: process.env.TEST_API_TOKEN || 'test-token-12345',
  invalidToken: 'invalid-token-xyz',
  uploaderId: 'test-uploader-e2e',
};

/**
 * Page helper methods
 */
export class UploadPageHelper {
  constructor(private page) {}

  async goto() {
    await this.page.goto('/');
  }

  async fillApiToken(token: string) {
    await this.page.fill('#apiToken', token);
  }

  async fillUploaderId(uploaderId: string) {
    await this.page.fill('#uploaderId', uploaderId);
  }

  async selectFile(filePath: string) {
    await this.page.locator('input[type="file"]').setInputFiles(filePath);
  }

  async clickUploadButton() {
    // Submit form directly using JavaScript
    await this.page.evaluate(() => {
      const form = document.getElementById('uploadForm') as HTMLFormElement;
      if (form && form.checkValidity()) {
        const submitEvent = new Event('submit', { bubbles: true, cancelable: true });
        form.dispatchEvent(submitEvent);
      } else if (form) {
        // If form not valid, still dispatch to trigger validation messages
        const submitEvent = new Event('submit', { bubbles: true, cancelable: true });
        form.dispatchEvent(submitEvent);
      }
    });
    await this.page.waitForTimeout(100);
  }

  async submitForm(options: {
    token?: string;
    uploaderId?: string;
    filePath?: string;
  } = {}) {
    if (options.token) {
      await this.fillApiToken(options.token);
    }
    if (options.uploaderId) {
      await this.fillUploaderId(options.uploaderId);
    }
    if (options.filePath) {
      await this.selectFile(options.filePath);
    }
    await this.clickUploadButton();
  }

  async getAlertMessage(): Promise<string | null> {
    try {
      const alert = this.page.locator('#alert');
      // Just check if alert has show class and return text, don't wait
      const className = await alert.getAttribute('class');
      if (className && className.includes('show')) {
        const text = await alert.textContent();
        return text ? text.trim() : null;
      }
      // If not shown, wait a bit
      await this.page.waitForFunction(
        () => {
          const el = document.getElementById('alert');
          return el && el.className && el.className.includes('show');
        },
        { timeout: 3000 }
      );
      const text = await alert.textContent();
      return text ? text.trim() : null;
    } catch (e) {
      // Alert didn't appear - return null
      return null;
    }
  }

  async waitForAlert(type: 'success' | 'error' | 'info' = 'success', timeout = 5000) {
    const alertClass = `alert show alert-${type}`;
    await this.page.waitForFunction(
      () => {
        const alert = document.getElementById('alert');
        return alert?.className === alertClass;
      },
      { timeout }
    );
  }

  async waitForProgressBar(timeout = 5000) {
    await this.page.waitForSelector('#progressContainer.show', { timeout });
  }

  async waitForStatusPanel(timeout = 10000) {
    await this.page.waitForSelector('#statusPanel.show', { timeout });
  }

  async getJobId(): Promise<string> {
    await this.waitForStatusPanel();
    return await this.page.textContent('#jobId') || '';
  }

  async getStatusValue(): Promise<string> {
    return await this.page.textContent('#statusValue') || '';
  }

  async getImageCount(): Promise<string> {
    return await this.page.textContent('#imageCount') || '0';
  }

  async waitForJobStatus(expectedStatus: 'PENDING' | 'PROCESSING' | 'COMPLETE' | 'PARTIAL' | 'FAILED', timeout = 60000) {
    await this.page.waitForFunction(
      (status) => {
        const statusEl = document.getElementById('statusValue');
        return statusEl?.textContent?.includes(status);
      },
      expectedStatus,
      { timeout }
    );
  }

  async getErrorCount(): Promise<number> {
    const errorText = await this.page.textContent('#errorsCount');
    return parseInt(errorText || '0', 10);
  }

  async toggleErrorsTable() {
    const toggle = this.page.locator('#errorsToggle');
    await toggle.waitFor({ state: 'visible', timeout: 2000 });
    await toggle.click();
    await this.page.waitForTimeout(100); // Small delay for DOM update
  }

  async getErrorTableRows(): Promise<number> {
    const rows = await this.page.locator('#errorsBody tr');
    return await rows.count();
  }

  async isUploadButtonDisabled(): Promise<boolean> {
    return await this.page.locator('#uploadBtn').isDisabled();
  }

  async isFormValid(): Promise<boolean> {
    const form = this.page.locator('#uploadForm');
    return await form.evaluate((f: HTMLFormElement) => f.checkValidity());
  }

  async clearForm() {
    await this.page.fill('#apiToken', '');
    await this.page.fill('#uploaderId', '');
  }

  async clearFileInput() {
    await this.page.locator('input[type="file"]').setInputFiles([]);
  }

  async waitForPageLoad() {
    await this.page.waitForLoadState('networkidle');
  }
}

/**
 * Mock API helper for testing without a real backend
 */
export async function setupMockApi(page) {
  // Mock the API responses
  await page.route('**/api/v1/uploads/', async (route) => {
    if (route.request().method() === 'POST') {
      // Mock successful upload response (202 Accepted)
      await route.abort('blockedbyclient');
      // In a real scenario, you'd use route.fulfill() to return mock data
    }
  });
}

/**
 * Wait for network idle (useful after form submission)
 */
export async function waitForNetworkIdle(page, timeout = 5000) {
  try {
    await page.waitForLoadState('networkidle', { timeout });
  } catch {
    // Network might not be fully idle, but that's okay for E2E tests
  }
}
