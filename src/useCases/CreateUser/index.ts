import { PostegresUsersRepository } from "./../../repositories/implementations/PostegresUsersRepository";
import { MailTrapProvider } from "../../providers/implementations/MailTrapProvider";
import { CreateUserCase } from "./CreateUserCase";
import { CreateUserController } from "./CreateUserController";

const mailreapMailProvider = new MailTrapProvider();
const postegresUsersRepository = new PostegresUsersRepository();
const createUserCase = new CreateUserCase(
  postegresUsersRepository,
  mailreapMailProvider
);

const createUserController = new CreateUserController(createUserCase);

export { createUserCase, createUserController };
