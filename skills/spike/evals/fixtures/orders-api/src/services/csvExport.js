import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { pool } from '../db.js';

const s3 = new S3Client({ region: process.env.AWS_REGION ?? 'eu-west-1' });

// Builds the whole CSV in memory, then uploads it. Fine for small ranges;
// a year of orders is ~1.2 GB and OOMs the 512 MB container.
export async function exportOrdersCsv(from, to) {
  const { rows } = await pool.query(
    'SELECT id, customer_id, total_cents, status, created_at FROM orders WHERE created_at BETWEEN $1 AND $2',
    [from, to],
  );
  let csv = 'id,customer_id,total_cents,status,created_at\n';
  for (const r of rows) csv += `${r.id},${r.customer_id},${r.total_cents},${r.status},${r.created_at.toISOString()}\n`;
  const key = `exports/orders-${Date.now()}.csv`;
  await s3.send(new PutObjectCommand({ Bucket: process.env.EXPORT_BUCKET, Key: key, Body: csv }));
  return key;
}
