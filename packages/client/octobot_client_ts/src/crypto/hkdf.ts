import { sha256 } from '@noble/hashes/sha2.js'
import { hkdf } from '@noble/hashes/hkdf.js'
import { utf8ToBytes } from '@noble/hashes/utils.js'

export function deriveAesKeyBytes(secret: string, salt: string, info: string): Uint8Array {
  return hkdf(sha256, utf8ToBytes(secret), utf8ToBytes(salt), utf8ToBytes(info), 32)
}
