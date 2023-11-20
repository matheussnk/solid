import { Request, Response } from "express";
import { CreateUserCase } from "./CreateUserCase";

export class CreateUserController {
  constructor(
    private createUserCase: CreateUserCase,
    ){}
  async handle(request: Request, response: Response): Promise<Response> {
    const { name, email, password } = request.body;
    try {
        await this.createUserCase.execute({
            name,
            email,
            password
        })   

        return response.status(201).send();
    }catch (err){
        return response.status(400).json({
            message: err.message || 'Unexpected error.'
        })

    }
}
}
