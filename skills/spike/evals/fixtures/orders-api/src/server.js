import express from 'express';
import { exportsRouter } from './routes/exports.js';
import { ordersRouter } from './routes/orders.js';

const app = express();
app.use(express.json());
app.use('/orders', ordersRouter);
app.use('/exports', exportsRouter);
app.listen(process.env.PORT ?? 3000);
