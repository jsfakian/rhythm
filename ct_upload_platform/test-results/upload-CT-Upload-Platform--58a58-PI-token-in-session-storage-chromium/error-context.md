# Page snapshot

```yaml
- generic [ref=e2]:
  - heading "CT Upload Platform" [level=1] [ref=e3]
  - paragraph [ref=e4]: Upload DICOM images for processing
  - generic [ref=e5]:
    - generic [ref=e6]:
      - generic [ref=e7]: API Token *
      - textbox "API Token *" [ref=e8]:
        - /placeholder: Enter your API token
      - generic [ref=e9]: Your token will be stored in this session only
    - generic [ref=e10]:
      - generic [ref=e11]: Uploader ID (Optional)
      - textbox "Uploader ID (Optional)" [ref=e12]:
        - /placeholder: Leave blank to use your username
      - generic [ref=e13]: If provided, will be recorded with this upload
    - generic [ref=e14]:
      - generic [ref=e15]: TAR File *
      - button "TAR File *" [ref=e16]
      - generic [ref=e17]: "Max size: 2048 MB | Format: .tar or .tar.gz"
    - button "Upload" [ref=e18] [cursor=pointer]
```