declare module 'pngjs' {
  export class PNG {
    constructor(options: { width: number; height: number })
    width: number
    height: number
    data: Buffer
    static sync: { read(input: Buffer): PNG; write(input: PNG): Buffer }
  }
}
