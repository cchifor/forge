export { default as DataTable } from './DataTable.vue'
export { default as ColumnManagerMenu } from './ColumnManagerMenu.vue'
export { useDataTable, twBelow, type PinSide } from './useDataTable'
export {
  useColumnManager,
  type ColumnManager,
  type ColumnManagerItem,
  type UseColumnManagerOptions,
} from './useColumnManager'
// Sub-composables — importable directly when a caller needs only one
// slice (visibility / order / pinning / sizing) without spinning up
// the full ``ColumnManager`` facade.
export {
  useColumnVisibility,
  type ColumnVisibility,
} from './useColumnVisibility'
export { useColumnOrder, type ColumnOrder } from './useColumnOrder'
export { useColumnPinning, type ColumnPinning } from './useColumnPinning'
export { useColumnSizing, type ColumnSizing } from './useColumnSizing'
export {
  DATA_TABLE_LAYOUT,
  type DataTableColumnDef,
  type DataTableColumnMeta,
  type DataTableLayout,
  type DataTableMode,
} from './types'
