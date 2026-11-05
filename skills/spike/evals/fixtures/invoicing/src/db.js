import knex from 'knex';
import config from '../knexfile.js';
// One shared pool for the whole app. Today there is exactly one company using it.
export const db = knex({ ...config, pool: { min: 2, max: 20 } });
