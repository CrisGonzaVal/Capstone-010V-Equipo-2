// Único environment versionable de la aplicación (Feature 006).
// No contiene secretos: la publishable key de Clerk es pública por diseño y se
// requiere en build time. No se usan `fileReplacements` ni environment de producción.
export const environment = {
  produccion: false,
  clerkPublishableKey:
    'pk_test_cmVsZXZhbnQtdGVybWl0ZS04MDg5LmNsZXJrLmFjY291bnRzLmRldiQ',
};
