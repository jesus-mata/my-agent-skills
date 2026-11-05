export async function up(knex) {
  await knex.schema.createTable('users', t => { t.increments('id'); t.string('email').unique(); t.timestamps(true, true); });
  await knex.schema.createTable('customers', t => { t.increments('id'); t.string('name'); t.string('vat_id'); });
  await knex.schema.createTable('invoices', t => {
    t.increments('id'); t.integer('customer_id').references('customers.id');
    t.integer('number').unique(); t.integer('total_cents'); t.string('status'); t.timestamps(true, true);
  });
  await knex.schema.createTable('invoice_lines', t => {
    t.increments('id'); t.integer('invoice_id').references('invoices.id'); t.string('description'); t.integer('amount_cents');
  });
}
export async function down() {}
