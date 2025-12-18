import express from 'express';
import multer from 'multer';
import axios from 'axios';
import FormData from 'form-data';
import archiver from 'archiver';
import morgan from 'morgan';
import { config } from './config.js';

import path from 'path';
import { fileURLToPath } from 'url';

// Lấy __dirname trong môi trường ES module
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);


const app = express();
app.get('/api/health', (req, res) => {
  return res.json({
    status: "ok",
    message: "Node API is running"
  });
});


app.use(morgan('dev'));
app.use(express.urlencoded({ extended: true }));
app.use(express.json());

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: config.maxFileSize, files: config.maxFilesPerRequest }
});

app.get('/api/health', (req, res) => res.json({ status: 'ok' }));

app.post('/api/v1/process', upload.array('file', config.maxFilesPerRequest), async (req, res) => {
  try {
    const files = req.files || [];
    if (!files.length) return res.status(400).json({ error: 'No file uploaded' });

    let options = {};
    if (req.body.options) options = JSON.parse(req.body.options);

    const tasks = files.map(file => {
      const formData = new FormData();
      formData.append('file', file.buffer, { filename: file.originalname, contentType: file.mimetype });
      formData.append('options', JSON.stringify(options));

      return axios.post(
        `${config.pythonEngineUrl}/process`,
        formData,
        { headers: formData.getHeaders(), responseType: 'arraybuffer' }
      ).then(response => ({
        buffer: Buffer.from(response.data),
        filename: response.headers['x-output-filename'] || file.originalname,
        contentType: response.headers['content-type'] || 'image/png'
      }));
    });

    const results = await Promise.all(tasks);

    if (results.length === 1) {
      const { buffer, filename, contentType } = results[0];
      res.setHeader('Content-Type', contentType);
      res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
      return res.send(buffer);
    }

    res.setHeader('Content-Disposition', 'attachment; filename="processed_images.zip"');
    res.setHeader('Content-Type', 'application/zip');

    const archive = archiver('zip', { zlib: { level: 9 } });
    archive.pipe(res);
    results.forEach(({ buffer, filename }) => archive.append(buffer, { name: filename }));
    archive.finalize();

  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'Internal server error', detail: err.message });
  }
});

// Phục vụ static files cho frontend
app.use(express.static(path.join(__dirname, '../public')));


// === NEW: API cho preview (trả base64) ===
app.post('/api/v1/process-preview', upload.array('file', config.maxFilesPerRequest), async (req, res) => {
  try {
    const files = req.files || [];
    if (!files.length) {
      return res.status(400).json({ error: 'No file uploaded' });
    }

    let options = {};
    if (req.body.options) {
      try {
        options = JSON.parse(req.body.options);
      } catch (e) {
        return res.status(400).json({ error: 'Invalid JSON in options' });
      }
    }

    const tasks = files.map((file) => {
      const formData = new FormData();
      formData.append('file', file.buffer, {
        filename: file.originalname,
        contentType: file.mimetype,
      });
      formData.append('options', JSON.stringify(options));

      return axios.post(`${config.pythonEngineUrl}/process`, formData, {
        headers: formData.getHeaders(),
        responseType: 'arraybuffer',
      }).then((response) => {
        const buffer = Buffer.from(response.data);
        const contentType = response.headers['content-type'] || 'image/png';
        const filename = response.headers['x-output-filename'] || file.originalname;
        const base64 = buffer.toString('base64');

        return {
          name: filename,
          mimeType: contentType,
          dataUrl: `data:${contentType};base64,${base64}`,
        };
      });
    });

    const previews = await Promise.all(tasks);
    return res.json({ files: previews });
  } catch (err) {
    console.error(err);
    return res.status(500).json({ error: 'Internal server error', detail: err.message });
  }
});


app.listen(config.port, () => console.log(`Node API listening on port ${config.port}`));
