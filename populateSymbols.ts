import { createClientFromRequest } from 'npm:@base44/sdk@0.8.20';
import postgres from 'npm:postgres@3.4.4';

const MASTER_SYMBOLS = [
  // Majors
  { name: "EURUSD", base: "EUR", quote: "USD", pip: 0.0001, size: 100000 },
  { name: "GBPUSD", base: "GBP", quote: "USD", pip: 0.0001, size: 100000 },
  { name: "USDJPY", base: "USD", quote: "JPY", pip: 0.01, size: 100000 },
  { name: "USDCHF", base: "USD", quote: "CHF", pip: 0.0001, size: 100000 },
  { name: "USDCAD", base: "USD", quote: "CAD", pip: 0.0001, size: 100000 },
  { name: "AUDUSD", base: "AUD", quote: "USD", pip: 0.0001, size: 100000 },
  { name: "NZDUSD", base: "NZD", quote: "USD", pip: 0.0001, size: 100000 },
  // EUR crosses
  { name: "EURGBP", base: "EUR", quote: "GBP", pip: 0.0001, size: 100000 },
  { name: "EURJPY", base: "EUR", quote: "JPY", pip: 0.01, size: 100000 },
  { name: "EURCHF", base: "EUR", quote: "CHF", pip: 0.0001, size: 100000 },
  { name: "EURCAD", base: "EUR", quote: "CAD", pip: 0.0001, size: 100000 },
  { name: "EURAUD", base: "EUR", quote: "AUD", pip: 0.0001, size: 100000 },
  { name: "EURNZD", base: "EUR", quote: "NZD", pip: 0.0001, size: 100000 },
  { name: "EURSGD", base: "EUR", quote: "SGD", pip: 0.0001, size: 100000 },
  // GBP crosses
  { name: "GBPJPY", base: "GBP", quote: "JPY", pip: 0.01, size: 100000 },
  { name: "GBPCHF", base: "GBP", quote: "CHF", pip: 0.0001, size: 100000 },
  { name: "GBPCAD", base: "GBP", quote: "CAD", pip: 0.0001, size: 100000 },
  { name: "GBPAUD", base: "GBP", quote: "AUD", pip: 0.0001, size: 100000 },
  { name: "GBPNZD", base: "GBP", quote: "NZD", pip: 0.0001, size: 100000 },
  { name: "GBPSGD", base: "GBP", quote: "SGD", pip: 0.0001, size: 100000 },
  // JPY crosses
  { name: "CHFJPY", base: "CHF", quote: "JPY", pip: 0.01, size: 100000 },
  { name: "CADJPY", base: "CAD", quote: "JPY", pip: 0.01, size: 100000 },
  { name: "AUDJPY", base: "AUD", quote: "JPY", pip: 0.01, size: 100000 },
  { name: "NZDJPY", base: "NZD", quote: "JPY", pip: 0.01, size: 100000 },
  { name: "SGDJPY", base: "SGD", quote: "JPY", pip: 0.01, size: 100000 },
  // Other crosses
  { name: "AUDCAD", base: "AUD", quote: "CAD", pip: 0.0001, size: 100000 },
  { name: "AUDCHF", base: "AUD", quote: "CHF", pip: 0.0001, size: 100000 },
  { name: "AUDNZD", base: "AUD", quote: "NZD", pip: 0.0001, size: 100000 },
  { name: "AUDSGD", base: "AUD", quote: "SGD", pip: 0.0001, size: 100000 },
  { name: "CADCHF", base: "CAD", quote: "CHF", pip: 0.0001, size: 100000 },
  { name: "NZDCAD", base: "NZD", quote: "CAD", pip: 0.0001, size: 100000 },
  { name: "NZDCHF", base: "NZD", quote: "CHF", pip: 0.0001, size: 100000 },
  { name: "CHFSGD", base: "CHF", quote: "SGD", pip: 0.0001, size: 100000 },
  { name: "USDSGD", base: "USD", quote: "SGD", pip: 0.0001, size: 100000 },
  // Commodities
  { name: "XAUUSD", base: "XAU", quote: "USD", pip: 0.01, size: 100 },
  { name: "XAGUSD", base: "XAG", quote: "USD", pip: 0.0001, size: 5000 },
  { name: "XTIUSD", base: "XTI", quote: "USD", pip: 0.01, size: 100 },
  { name: "XBRUSD", base: "XBR", quote: "USD", pip: 0.01, size: 100 },
  { name: "XNGUSD", base: "XNG", quote: "USD", pip: 0.001, size: 10000 },
  { name: "XPTUSD", base: "XPT", quote: "USD", pip: 0.01, size: 100 },
  { name: "XPDUSD", base: "XPD", quote: "USD", pip: 0.01, size: 100 },
  // Indices
  { name: "US30", base: "US30", quote: "USD", pip: 1, size: 1 },
  { name: "US500", base: "US500", quote: "USD", pip: 0.1, size: 1 },
  { name: "USTEC", base: "USTEC", quote: "USD", pip: 1, size: 1 },
  { name: "UK100", base: "UK100", quote: "GBP", pip: 1, size: 1 },
  { name: "DE40", base: "DE40", quote: "EUR", pip: 1, size: 1 },
  { name: "JP225", base: "JP225", quote: "JPY", pip: 1, size: 1 },
  { name: "STOXX50", base: "STOXX50", quote: "EUR", pip: 1, size: 1 },
  { name: "F40", base: "F40", quote: "EUR", pip: 1, size: 1 },
  { name: "AUS200", base: "AUS200", quote: "AUD", pip: 1, size: 1 }
];

Deno.serve(async (req) => {
  try {
    const base44 = createClientFromRequest(req);
    const user = await base44.auth.me();
    
    if (user?.role !== 'admin') {
      return Response.json({ error: 'Admin access required' }, { status: 403 });
    }

    const host = Deno.env.get('CLOUD_SQL_HOST');
    const dbName = Deno.env.get('CLOUD_SQL_DB_NAME');
    const dbUser = Deno.env.get('CLOUD_SQL_DB_USER');
    const password = Deno.env.get('CLOUD_SQL_DB_PASSWORD');

    const sql = postgres({
      host,
      database: dbName,
      username: dbUser,
      password,
      ssl: true
    });

    try {
      // Clear existing symbols
      await sql`DELETE FROM symbols`;

      // Bulk insert all symbols
      for (const sym of MASTER_SYMBOLS) {
        await sql`
          INSERT INTO symbols (name, "baseAssetId", "quoteAssetId", pip_value, contract_size)
          VALUES (${sym.name}, ${sym.base}, ${sym.quote}, ${sym.pip}, ${sym.size})
        `;
      }

      const count = await sql`SELECT COUNT(*) as total FROM symbols`;

      return Response.json({
        status: 'success',
        message: `Populated ${count[0].total} symbols`,
        symbols_inserted: MASTER_SYMBOLS.length
      });
    } finally {
      await sql.end();
    }
  } catch (error) {
    return Response.json({ 
      error: error.message,
      status: 'failed'
    }, { status: 500 });
  }
});
