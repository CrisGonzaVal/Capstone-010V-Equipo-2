# Constitución: Misión y Alcance del Producto

## 1. Problema de Negocio
Las organizaciones con sedes distribuidas sufren desabastecimiento crítico, duplicidad de pedidos de insumos de ofimática y pérdida de trazabilidad entre lo solicitado por departamentos internos y el stock real resguardado en bodega.

## 2. Propósito de Compustock ERP
Proveer una solución integral y modular que digitalice el ciclo de vida del suministro de materiales de oficina: desde el catálogo disponible y la solicitud departamental vía tickets interactivos, hasta la preparación física, despacho con rebaja automática de existencias y reportabilidad ejecutiva.

## 3. Actores del Sistema
- **Superadmin**: Administrador global del SaaS; aprovisiona instituciones/sedes y audita métricas del sistema.
- **Administrador Institucional**: Gestiona usuarios, departamentos y el catálogo maestro de categorías e insumos.
- **Bodeguero / Encargado de Suministros**: Gestiona stock físico, supervisa el tablero Kanban y despacha pedidos aprobados rebajando el inventario.
- **Solicitante (Funcionario)**: Consulta disponibilidad de insumos en tiempo real y emite tickets de requerimiento justificados para su departamento.

## 4. Principios Inmutables del Sistema
1. **Prioridad a la Operación de Insumos**: La funcionalidad operativa de tickets y control de stock es el núcleo del negocio y se construye de forma prioritaria sobre la infraestructura SaaS.
2. **Trazabilidad Absoluta**: Ningún insumo puede aumentar o disminuir su stock sin generar un registro inmutable en la tabla de auditoría `movimientos_inventario`.
3. **Consistencia Transaccional**: El despacho de un pedido debe rebajar existencias y cambiar el estado del ticket dentro de una misma transacción ACID; si una operación falla, se revierte por completo.