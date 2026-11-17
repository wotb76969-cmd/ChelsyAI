/* Chelsy Group 0.9.4 — own Host Auth. Never put secret keys here.
   Point apiBase at your Chelsy Host HTTPS origin (same origin preferred). */
window.CHELSY_CONFIG = {
  apiBase: '',  // empty = same origin; or 'https://host.example.com'
  authMode: 'own',
  // Legacy Supabase keys kept only for read-only migration pages; productive cabinet does not use them.
  supabaseUrl: '',
  supabasePublishableKey: ''
};
