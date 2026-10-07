import { expect, it } from 'vitest'
import { HTTPError } from 'ky'
import { formatDetail, unpackApiError, unpackApiErrorMessage } from './errors'

function httpError(body: string, status = 422) {
  return new HTTPError(new Response(body, { status }), new Request('http://localhost/api'), {} as never)
}

it('normalizes platform and legacy validation envelopes', async () => {
  const info = await unpackApiError(httpError(JSON.stringify({ message: 'Name required', type: 'ValidationError', detail: { code: 422 } })))
  expect(info).toEqual({ message: 'Name required', type: 'ValidationError', status: 422, detail: { code: 422 } })
  expect(formatDetail({ detail: 'Invalid name' })).toBe('Invalid name')
  expect(formatDetail({ detail: [null, 1, { loc: ['body', 'name'], msg: 'required' }, { msg: 'invalid' }, {}] })).toBe('name: required · invalid · invalid')
  expect(formatDetail({ detail: [{ loc: [], msg: 'required' }] })).toBe('required')
  expect(formatDetail({ message: ' ', detail: [] })).toBeNull()
  expect(formatDetail(null)).toBeNull()
})

it('does not expose unrecognized HTTP response bodies', async () => {
  for (const body of ['secret upstream body', '{}', 'null']) {
    expect(await unpackApiErrorMessage(httpError(body, 500))).toBe('Request failed (500).')
  }
  expect(await unpackApiError(new Error('Local failure'))).toEqual({ message: 'Local failure' })
  expect(await unpackApiError('offline')).toEqual({ message: 'offline' })
})
