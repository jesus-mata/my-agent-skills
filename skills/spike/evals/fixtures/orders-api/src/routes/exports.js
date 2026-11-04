import { Router } from 'express';
import { exportOrdersCsv } from '../services/csvExport.js';
export const exportsRouter = Router();
exportsRouter.post('/orders', async (req, res) => {
  const key = await exportOrdersCsv(req.body.from, req.body.to);
  res.json({ key });
});
