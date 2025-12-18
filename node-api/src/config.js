import dotenv from 'dotenv';
dotenv.config();

export const config = {
  port: process.env.PORT || 3000,
  pythonEngineUrl: process.env.PYTHON_ENGINE_URL || 'http://127.0.0.1:5001',
  maxFileSize: 15 * 1024 * 1024,
  maxFilesPerRequest: 20
};
