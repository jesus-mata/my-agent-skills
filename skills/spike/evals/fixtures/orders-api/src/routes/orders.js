import { Router } from 'express';
import { pool } from '../db.js';
export const ordersRouter = Router();
ordersRouter.get('/', async (req, res) => {
  const { rows } = await pool.query('SELECT * FROM orders ORDER BY created_at DESC LIMIT 100');
  res.json(rows);
});
// Clients poll this every 5s to see order status changes.
ordersRouter.get('/:id/status', async (req, res) => {
  const { rows } = await pool.query('SELECT status FROM orders WHERE id = $1', [req.params.id]);
  res.json(rows[0] ?? null);
});
