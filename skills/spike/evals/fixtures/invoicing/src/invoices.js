import { db } from './db.js';
export const listInvoices = () => db('invoices').orderBy('created_at', 'desc');
export const nextInvoiceNumber = async () => ((await db('invoices').max('number as n').first()).n ?? 0) + 1;
export const reportRevenue = () => db.raw('SELECT date_trunc(\'month\', created_at) m, sum(total_cents) FROM invoices GROUP BY 1');
