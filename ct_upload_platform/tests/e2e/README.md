# Playwright E2E Tests for CT Upload Platform

This directory contains comprehensive end-to-end tests for the CT Upload Platform UI using Playwright.

## Setup

### 1. Install Playwright

```bash
# Install Playwright and its dependencies
npm install -D @playwright/test

# Install browsers (Chrome, Firefox, Safari)
npx playwright install
```

### 2. Install Dependencies

```bash
# Install Python requirements (already includes playwright in requirements.txt)
pip install -r requirements.txt
```

### 3. Start the Django Server

Before running tests, make sure the Django development server is running:

```bash
cd ct_upload_platform
python manage.py runserver
```

Or use the Makefile:

```bash
make dev
```

The server should be accessible at `http://localhost:8000`

## Running Tests

### Run All Tests

```bash
npx playwright test
```

### Run Tests with UI Mode (Recommended for Development)

```bash
npx playwright test --ui
```

This launches an interactive UI where you can:
- View test execution in real-time
- Step through tests
- Inspect DOM elements
- View network requests and responses

### Run Tests in Headed Mode (See the Browser)

```bash
npx playwright test --headed
```

### Run Specific Test File

```bash
npx playwright test tests/e2e/upload.spec.ts
```

### Run Specific Test Suite

```bash
# Run only form validation tests
npx playwright test --grep "Form Validation"

# Run only upload flow tests
npx playwright test --grep "Upload Flow"
```

### Run Tests in Specific Browser

```bash
# Chromium only
npx playwright test --project=chromium

# Firefox only
npx playwright test --project=firefox

# Safari only
npx playwright test --project=webkit

# Mobile Chrome
npx playwright test --project="Mobile Chrome"
```

### Debug Tests

```bash
# Run with debug mode (opens Inspector)
npx playwright test --debug

# Or use Node debugger
node --inspect-brk ./node_modules/.bin/playwright test
```

## Test Structure

### Test Files

- **`tests/e2e/upload.spec.ts`** - Main UI test suite
  - Form validation tests
  - Form UI interactions
  - Upload flow tests
  - Status tracking tests
  - Alert message tests
  - Responsive design tests
  - Accessibility tests
  - Error handling tests
  - Session management tests

- **`tests/e2e/fixtures.ts`** - Test utilities and helpers
  - `UploadPageHelper` - Helper methods for interacting with the upload page
  - Test data generator functions
  - Mock API helpers
  - Test credentials

### Test Categories

1. **Form Validation** - Tests that verify form validation logic
   - Missing API token
   - Missing file
   - Invalid file extensions
   - File size validation

2. **Form UI Interactions** - Tests for form interactive features
   - Session storage of tokens
   - Form disable/enable during upload
   - Optional/required field indicators

3. **Upload Flow** - Tests for the upload process
   - Progress bar visibility
   - Invalid token handling
   - Status panel population

4. **Status Tracking** - Tests for job status updates
   - Job ID display
   - Status value changes
   - Image count display
   - Error section visibility and interaction

5. **Alert Messages** - Tests for notification system
   - Success alerts
   - Error alerts
   - Info alerts

6. **Responsive Design** - Tests on different viewports
   - Mobile (375x667)
   - Tablet (768x1024)
   - Desktop (1280x720)

7. **Accessibility** - Tests for accessibility compliance
   - Form labels
   - Field hints
   - Placeholders
   - CSRF token

8. **Error Handling** - Tests for error scenarios
   - Network errors
   - Server errors
   - Multiple uploads

## Configuration

### Environment Variables

Set these to customize test behavior:

```bash
# API token for authentication (defaults to 'test-token-12345')
export TEST_API_TOKEN="your-actual-test-token"

# Run tests in CI mode (no UI, headless)
export CI=true
```

### Playwright Configuration

See `playwright.config.ts` for detailed configuration:

- **Base URL**: http://localhost:8000
- **Timeout**: 30 seconds per test
- **Screenshot**: Captured on test failure
- **Video**: Recorded on test failure
- **Trace**: Recorded on first retry
- **Browsers**: Chromium, Firefox, webkit, Mobile Chrome, Mobile Safari

## Troubleshooting

### Tests Won't Run

**Problem**: Command not found: `npx`
- **Solution**: Make sure Node.js is installed (`node --version`)

**Problem**: Port 8000 already in use
- **Solution**: Either stop the process using port 8000 or change port in `playwright.config.ts`

### Tests Fail with Network Errors

**Problem**: Tests fail with "connection refused"
- **Solution**: Ensure Django server is running on http://localhost:8000

**Problem**: Tests timeout waiting for elements
- **Solution**: 
  - Increase timeout in `playwright.config.ts`
  - Check browser console for JavaScript errors
  - Run with `--debug` flag for investigation

### Authentication Issues

**Problem**: Tests fail with "Invalid API token"
- **Solution**: 
  - Set valid `TEST_API_TOKEN` environment variable
  - Or modify `TEST_CREDENTIALS` in `tests/e2e/fixtures.ts`
  - Ensure test API token has upload permissions

### Browser Issues

**Problem**: "Browser not found"
- **Solution**: Run `npx playwright install`

**Problem**: "Permission denied" on macOS
- **Solution**: `xattr -d com.apple.quarantine ~/Library/Caches/ms-playwright-shell/*/chrome_executable`

## Viewing Test Reports

After tests run, view the HTML report:

```bash
npx playwright show-report
```

This shows:
- Test results overview
- Per-test timing
- Screenshots and videos
- Trace files for debugging

## Writing New Tests

### Template for New Test

```typescript
test('should do something specific', async ({ page, testDataDir }) => {
  uploadHelper = new UploadPageHelper(page);
  await uploadHelper.goto();

  // Arrange
  const tarPath = await createTestTarArchive(testDataDir);
  
  // Act
  await uploadHelper.fillApiToken(TEST_CREDENTIALS.validToken);
  await uploadHelper.selectFile(tarPath);
  await uploadHelper.clickUploadButton();

  // Assert
  const message = await uploadHelper.getAlertMessage();
  expect(message).toContain('expected text');
});
```

### Available Helper Methods

```typescript
uploadHelper.goto()                          // Navigate to upload page
uploadHelper.fillApiToken(token)             // Fill API token field
uploadHelper.fillUploaderId(id)              // Fill uploader ID field
uploadHelper.selectFile(path)                // Select file to upload
uploadHelper.clickUploadButton()             // Click upload button
uploadHelper.getAlertMessage()               // Get current alert text
uploadHelper.waitForAlert(type, timeout)     // Wait for alert of type
uploadHelper.waitForStatusPanel(timeout)     // Wait for status panel
uploadHelper.getJobId()                      // Get job ID from status
uploadHelper.getStatusValue()                // Get current status
uploadHelper.getImageCount()                 // Get processed image count
uploadHelper.getErrorCount()                 // Get error count
uploadHelper.toggleErrorsTable()             // Toggle error table visibility
```

## CI/CD Integration

For GitHub Actions or similar:

```yaml
- name: Install Playwright
  run: npx playwright install --with-deps

- name: Run E2E Tests
  run: npx playwright test
  env:
    CI: true
    TEST_API_TOKEN: ${{ secrets.TEST_API_TOKEN }}
```

## Best Practices

1. **Use Page Helpers** - Use `UploadPageHelper` instead of raw selectors
2. **Wait for Elements** - Don't use arbitrary timeouts; use `waitFor*` methods
3. **Test User Flows** - Test what users actually do, not implementation details
4. **Isolate Tests** - Each test should be independent and not depend on others
5. **Clean Up** - Playwright handles cleanup, but clean test data if needed
6. **Use Fixtures** - Leverage Playwright's fixture system for setup/teardown
7. **Meaningful Assertions** - Assert on visible behavior, not internal state

## Performance Tips

1. **Parallel Execution** - Tests run in parallel by default (controlled by `workers`)
2. **Headed vs Headless** - Headless is faster; use for CI
3. **Browser Choice** - Chromium is fastest; use for quick feedback
4. **Reduce Video Recording** - Only record on failure (configured in `playwright.config.ts`)

## Additional Resources

- [Playwright Documentation](https://playwright.dev)
- [Playwright Test Framework](https://playwright.dev/docs/intro)
- [Selectors Guide](https://playwright.dev/docs/selectors)
- [Debugging Guide](https://playwright.dev/docs/debug)
- [Inspector Guide](https://playwright.dev/docs/inspector)

## Contributing

When adding new tests:

1. Follow existing naming conventions
2. Group related tests in `test.describe()` blocks
3. Add comments explaining complex test logic
4. Update this README if adding new test categories
5. Ensure tests are deterministic (no flakiness)
6. Test both happy path and error scenarios
