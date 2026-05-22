# Page snapshot

```yaml
- generic [ref=e2]:
  - heading "CT Upload Platform" [level=1] [ref=e3]
  - paragraph [ref=e4]: Upload DICOM images for processing
  - generic [ref=e5]: Invalid API token (401 Unauthorized)
  - generic [ref=e6]:
    - generic [ref=e7]:
      - generic [ref=e8]: API Token *
      - textbox "API Token *" [active] [ref=e9]:
        - /placeholder: Enter your API token
        - text: test-token-12345
      - generic [ref=e10]: Your token will be stored in this session only
    - generic [ref=e11]:
      - generic [ref=e12]: Uploader ID (Optional)
      - textbox "Uploader ID (Optional)" [ref=e13]:
        - /placeholder: Leave blank to use your username
      - generic [ref=e14]: If provided, will be recorded with this upload
    - generic [ref=e15]:
      - generic [ref=e16]: TAR File *
      - button "TAR File *" [ref=e17]
      - generic [ref=e18]: "Max size: 2048 MB | Format: .tar or .tar.gz"
    - button "Upload" [ref=e19] [cursor=pointer]
```