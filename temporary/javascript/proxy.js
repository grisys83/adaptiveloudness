// proxy-server.js
  const express = require('express');
  const cors = require('cors');
  const { createProxyMiddleware } = require('http-proxy-middleware');

  const app = express();

  app.use(cors({
    origin: 'http://grisys.synology.me'
  }));

  app.use('/music', express.static('/path/to/music/files'));

  app.listen(8080);
