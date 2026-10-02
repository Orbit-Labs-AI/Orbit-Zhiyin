import { Ajv } from 'ajv';
import { readFileSync } from 'node:fs';
import type { StandardEvent } from './types.ts';

export const eventSchema = JSON.parse(readFileSync(new URL('../schema/events.schema.json',import.meta.url),'utf8'));
const validate = new Ajv({ allErrors: true, strict: false }).compile(eventSchema);
export function validateEvent(event: StandardEvent): void {
  const kind = event.kind;
  if (!validate(event)) throw new Error(`Invalid ${kind}: ${JSON.stringify(validate.errors)}`);
}
