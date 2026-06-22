# QSF file format
JSON-like with the following payload format:
- `"SurveyEntry"` -> survey metadata (name, creation, expiry, status, etc.)
- `"SurveyElements"` -> actual survey components
    - `"Element": "BL"` -> `"Primary Attribute": "Survey Blocks"` (the actual blocks + trash)
    - `"Element": "FL"` -> `"Primary Attribute": "Survey Flow"`
    - `"Element": "NT"` -> comments
    - `"Element": "PL"` -> `"Primary Attribute": "Preview Link"`
    - `"Element": "PROJ"` -> `"Primary Attribute": "CORE"`
    - `"Element": "QC"` -> `"Primary Attribute": "Survey Question Count"`
    - `"Element": "RS"` -> response set
    - `"Element": "SCO"` -> `"Primary Attribute": "Scoring"`
    - `"Element": "SO"` -> `"Primary Attribute": "Survey Options"`
    - `"Element": "SQ"` -> survey question (with QID as `"Primary Attribute"`) one for each question 
    - `"Element": "STAT"` -> `"Primary Attribute": "Survey Statistics"`