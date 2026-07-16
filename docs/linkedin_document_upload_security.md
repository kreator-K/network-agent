# LinkedIn Document Upload Security

Only approved PDF, DOC/DOCX, and PPT/PPTX files are eligible. File path, MIME,
size, hash, and title are frozen. The authenticated member owns initialization,
temporary upload URLs are neither logged nor stored, and only the provider URN
from the current request may enter the final post payload.
