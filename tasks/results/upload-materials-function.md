# Result: upload-materials-function

**Status**: ✅ Complete

## What was done
- Created `src/functions/upload_materials/__init__.py`
- POST /api/upload-materials — multipart; accepts file OR sharepoint_url
- Uploads bytes to examops-input blob
- Extracts text and upserts into Azure AI Search materials index via FileHandlerAgent.index_document_in_search()
- Updates session.materials_urls list
- Returns {session_id, materials_count}
